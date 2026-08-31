import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


GITHUB_USERNAME = "azevedtheo"

# Shown in the STACK row. Edit this list as the toolkit changes.
STACK = ["Proxmox", "Git", "Wireshark", "Python"]

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "profile.json"
README_FILE = ROOT / "README.md"

TELEMETRY_START = "<!-- TELEMETRY_START -->"
TELEMETRY_END = "<!-- TELEMETRY_END -->"

API_URL = "https://api.github.com"

# The commit/lines-changed stats below hit an endpoint that's much more
# reliable (and 5000/hr instead of 60/hr) with a token attached. In GitHub
# Actions this is free - the default GITHUB_TOKEN is already injected as an
# env var, no secret to create. Running locally, export a classic PAT with
# no scopes needed (public repo stats are, well, public).
_TOKEN = os.environ.get("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {_TOKEN}"} if _TOKEN else {}

# Fixed layout width. Every row is padded/truncated to this many
# characters so the box always closes cleanly regardless of content.
WIDTH = 46
CONTENT_WIDTH = WIDTH - 2


def get_repositories() -> list[dict]:
    repositories = []
    page = 1

    while True:
        response = requests.get(
            f"{API_URL}/users/{GITHUB_USERNAME}/repos",
            params={
                "per_page": 100,
                "page": page,
                "type": "owner",
            },
            headers=HEADERS,
            timeout=30,
        )
        response.raise_for_status()

        batch = response.json()

        if not batch:
            break

        repositories.extend(batch)
        page += 1

    return repositories


def get_languages(repo_full_name: str) -> dict[str, int]:
    response = requests.get(
        f"{API_URL}/repos/{repo_full_name}/languages",
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    return response.json()


def get_issue_and_pr_counts(repo_full_name: str) -> tuple[int, int]:
    """Return (open_issues, open_pull_requests) for a repo.

    GitHub's repo.open_issues_count bundles issues *and* pull requests
    together, so it can't be trusted for either number on its own. The
    /issues endpoint returns both types too, but each pull request in
    that list carries a "pull_request" key that plain issues don't -
    that's what separates the two counts below.
    """
    response = requests.get(
        f"{API_URL}/repos/{repo_full_name}/issues",
        params={"state": "open", "per_page": 100},
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    items = response.json()
    open_prs = sum(1 for item in items if "pull_request" in item)
    open_issues = len(items) - open_prs

    return open_issues, open_prs


def get_commit_and_line_stats(repo_full_name: str) -> dict[str, int]:
    """Return {"commits", "additions", "deletions"} totals for a repo.

    /stats/contributors is the only REST endpoint that gives lines-changed
    without walking every commit by hand. It returns each contributor's
    activity broken into weeks, so summing every week's "a" (additions),
    "d" (deletions), and "c" (commits) across all contributors gives the
    repo-wide totals.

    GitHub computes these stats asynchronously and caches them. On a repo
    it hasn't seen queried recently, the first request returns 202 with an
    empty body while it builds the cache - so this retries with a short
    wait instead of treating that as "no data".
    """
    url = f"{API_URL}/repos/{repo_full_name}/stats/contributors"

    for attempt in range(6):
        response = requests.get(url, headers=HEADERS, timeout=30)

        if response.status_code == 202:
            time.sleep(2)
            continue

        response.raise_for_status()
        contributors = response.json() or []

        commits = additions = deletions = 0
        for contributor in contributors:
            for week in contributor.get("weeks", []):
                commits += week.get("c", 0)
                additions += week.get("a", 0)
                deletions += week.get("d", 0)

        return {"commits": commits, "additions": additions, "deletions": deletions}

    # Gave up waiting for GitHub to finish computing the cache. Rare, but
    # better to show zeros for one run than to fail the whole sync.
    return {"commits": 0, "additions": 0, "deletions": 0}


def collect_data() -> dict:
    repositories = get_repositories()

    language_totals: dict[str, int] = {}
    stars = 0
    forks = 0
    open_issues = 0
    open_prs = 0
    commits = 0
    additions = 0
    deletions = 0

    for repo in repositories:
        stars += repo.get("stargazers_count", 0)
        forks += repo.get("forks_count", 0)

        repo_languages = get_languages(repo["full_name"])
        for language, bytes_count in repo_languages.items():
            language_totals[language] = (
                language_totals.get(language, 0) + bytes_count
            )

        issues, prs = get_issue_and_pr_counts(repo["full_name"])
        open_issues += issues
        open_prs += prs

        code_stats = get_commit_and_line_stats(repo["full_name"])
        commits += code_stats["commits"]
        additions += code_stats["additions"]
        deletions += code_stats["deletions"]

    total_language_bytes = sum(language_totals.values())

    language_percentages = {}

    if total_language_bytes:
        for language, bytes_count in sorted(
            language_totals.items(),
            key=lambda item: item[1],
            reverse=True,
        ):
            language_percentages[language] = round(
                bytes_count / total_language_bytes * 100,
                1,
            )

    return {
        "repositories": len(repositories),
        "stars": stars,
        "forks": forks,
        "open_issues": open_issues,
        "open_prs": open_prs,
        "commits": commits,
        "additions": additions,
        "deletions": deletions,
        "languages": language_percentages,
        "last_sync": datetime.now(timezone.utc).isoformat(),
    }


def save_json(data: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    DATA_FILE.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Rendering
#
# Every helper below returns a string exactly CONTENT_WIDTH characters wide,
# so "row(...)" can wrap it in the side borders without ever miscounting.
# The one thing to avoid inside the box: emoji or other double-width glyphs.
# They report len() == 1 in Python but draw as 2 columns in a monospace
# font, which silently shifts every border after them - that was the bug
# in the original card.
# ---------------------------------------------------------------------------


def row(content: str = "") -> str:
    content = content[:CONTENT_WIDTH]
    return f"║ {content:<{CONTENT_WIDTH}} ║"


def divider() -> str:
    return "╟" + "─" * WIDTH + "╢"


def centered_row(content: str) -> str:
    return row(content.center(CONTENT_WIDTH))


def stat_line(label: str, value) -> str:
    value_text = str(value)
    dots = "." * (CONTENT_WIDTH - len(label) - len(value_text) - 2)
    return row(f"{label} {dots} {value_text}")


def format_count(n: int) -> str:
    """1234 -> '1.2K', 15200 -> '15.2K'. Small numbers stay as-is."""
    if n < 1000:
        return str(n)
    return f"{n / 1000:.1f}K"


def language_bar(index: int, language: str, percentage: float) -> str:
    bar_width = 18
    filled = round((percentage / 100) * bar_width)
    bar = "█" * filled + "░" * (bar_width - filled)
    content = (
        f"{index:02d} {language:<10} {bar} {percentage:>5.1f}%"
    )
    return row(content)


def wrap_stack(items: list[str], sep: str = " · ") -> list[str]:
    lines: list[str] = []
    current = ""
    inner_width = CONTENT_WIDTH - 2

    for item in items:
        candidate = item if not current else current + sep + item
        if len(candidate) <= inner_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = item

    if current:
        lines.append(current)

    return lines


def generate_telemetry(data: dict) -> str:
    languages = data["languages"]

    lines = [
        "```text",
        "╔" + "═" * WIDTH + "╗",
        centered_row("MOISES // TELEMETRY"),
        "╠" + "═" * WIDTH + "╣",
        row(),
        stat_line("REPOSITORIES", data["repositories"]),
        stat_line("STARS", data["stars"]),
        stat_line("FORKS", data["forks"]),
        stat_line("OPEN ISSUES", data["open_issues"]),
        stat_line("OPEN PULL REQUESTS", data["open_prs"]),
        row(),
        divider(),
        row(),
        row("CODE"),
        row(),
        stat_line("COMMITS", data["commits"]),
        stat_line("LINES ADDED", format_count(data["additions"])),
        stat_line("LINES REMOVED", format_count(data["deletions"])),
        row(),
        divider(),
        row(),
        row("LANGUAGE RANKING"),
        row(),
    ]

    for index, (language, percentage) in enumerate(
        list(languages.items())[:5],
        start=1,
    ):
        lines.append(language_bar(index, language, percentage))

    lines.append(row())
    lines.append(divider())
    lines.append(row())
    lines.append(row("STACK"))
    lines.append(row())
    for stack_line in wrap_stack(STACK):
        lines.append(row(f"  {stack_line}"))
    lines.append(row())
    lines.append(divider())
    lines.append(row())

    sync_display = data["last_sync"][:16].replace("T", "  ") + " UTC"
    lines.append(row(f"LAST SYNC   {sync_display}"))
    lines.append("╚" + "═" * WIDTH + "╝")
    lines.append("```")

    return "\n".join(lines)


def update_readme(telemetry: str) -> None:
    readme = README_FILE.read_text(encoding="utf-8")

    start = readme.find(TELEMETRY_START)
    end = readme.find(TELEMETRY_END)

    if start == -1 or end == -1:
        raise RuntimeError(
            "README.md is missing TELEMETRY_START / TELEMETRY_END markers."
        )

    centered_block = f'<div align="center">\n\n{telemetry}\n\n</div>'

    new_readme = (
        readme[: start + len(TELEMETRY_START)]
        + "\n\n"
        + centered_block
        + "\n\n"
        + readme[end:]
    )

    README_FILE.write_text(new_readme, encoding="utf-8")


def main() -> None:
    print("Starting GitHub telemetry...")

    print("Fetching repositories...")
    data = collect_data()

    print(f"Found {data['repositories']} repositories")

    print("Saving profile.json...")
    save_json(data)

    print("Generating README telemetry...")
    telemetry = generate_telemetry(data)

    print("Updating README.md...")
    update_readme(telemetry)

    print("Telemetry updated successfully!")


if __name__ == "__main__":
    main()
