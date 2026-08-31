import json
from datetime import datetime, timezone
from pathlib import Path

import requests


GITHUB_USERNAME = "azevedtheo"

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "profile.json"
README_FILE = ROOT / "README.md"

TELEMETRY_START = "<!-- TELEMETRY_START -->"
TELEMETRY_END = "<!-- TELEMETRY_END -->"

API_URL = "https://api.github.com"


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
        timeout=30,
    )
    response.raise_for_status()

    return response.json()


def collect_data() -> dict:
    repositories = get_repositories()

    language_totals: dict[str, int] = {}

    for repo in repositories:
        repo_languages = get_languages(repo["full_name"])

        for language, bytes_count in repo_languages.items():
            language_totals[language] = (
                language_totals.get(language, 0) + bytes_count
            )

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
        "languages": language_percentages,
        "last_sync": datetime.now(timezone.utc).isoformat(),
    }


def save_json(data: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    DATA_FILE.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )


def generate_telemetry(data: dict) -> str:
    repositories = data["repositories"]
    languages = data["languages"]

    lines = [
        "```text",
        "╔══════════════════════════════════════════════╗",
        "║              MOISES // TELEMETRY             ║",
        "╠══════════════════════════════════════════════╣",
        "║                                              ║",
        f"║  REPOSITORIES                    {repositories:>8}     ║",
        "║                                              ║",
        "║  ───── LANGUAGE RANKING ─────                ║",
    ]

    for index, (language, percentage) in enumerate(
        list(languages.items())[:5],
        start=1,
    ):
        bar_length = int(percentage / 4)
        bar = "█" * bar_length

        lines.append(
            f"║  {index:02d}  {language:<14} "
            f"{bar:<12} {percentage:>5.1f}%     ║"
        )

    lines.extend(
        [
            "║                                              ║",
            f"║  LAST SYNC: {data['last_sync']:<30}║",
            "╚══════════════════════════════════════════════╝",
            "```",
        ]
    )

    return "\n".join(lines)


def update_readme(telemetry: str) -> None:
    readme = README_FILE.read_text(encoding="utf-8")

    start = readme.find(TELEMETRY_START)
    end = readme.find(TELEMETRY_END)

    if start == -1 or end == -1:
        raise RuntimeError(
            "README.md is missing TELEMETRY_START / TELEMETRY_END markers."
        )

    new_readme = (
        readme[: start + len(TELEMETRY_START)]
        + "\n\n"
        + telemetry
        + "\n\n"
        + readme[end:]
    )

    README_FILE.write_text(new_readme, encoding="utf-8")


def main() -> None:
    print("🚀 Starting GitHub telemetry...")

    print("📡 Fetching repositories...")
    data = collect_data()

    print(f"✅ Found {data['repositories']} repositories")

    print("💾 Saving profile.json...")
    save_json(data)

    print("📝 Generating README telemetry...")
    telemetry = generate_telemetry(data)

    print("📖 Updating README.md...")
    update_readme(telemetry)

    print("✅ Telemetry updated successfully!")


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()