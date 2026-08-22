"""Daily checkpoint logging for the content pipeline.

Writes a structured CURRENT.md-style log after each daily run so the user can
resume, debug, or audit without scrolling CLI output.
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config.settings import DATA_DIR
from pipeline.invariants import HealthCheck


CHECKPOINT_DIR = DATA_DIR / "daily-runs"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def ensure_checkpoint_dir() -> None:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)


def write_daily_checkpoint(
    *,
    collected: int,
    worthy: int,
    drafted: int,
    newsletter_sections: int,
    verified: int = 0,
    rejected: int = 0,
    source_errors: list[str] | None = None,
    health_checks: list[HealthCheck] | None = None,
    next_action: str = "Review queue with `python run.py queue`",
) -> Path:
    """Write today's checkpoint and update CURRENT.md."""
    ensure_checkpoint_dir()
    date = _date_str()
    timestamp = _now()

    source_errors = source_errors or []
    health_checks = health_checks or []

    content = f"""# Daily Run — {date}

- timestamp: {timestamp}
- collected: {collected}
- worthy: {worthy}
- drafted: {drafted}
- newsletter_sections: {newsletter_sections}
- verified: {verified}
- rejected: {rejected}
- source_errors: {len(source_errors)}
- next_action: {next_action}

## Source errors
"""
    if source_errors:
        for err in source_errors:
            content += f"- {err}\n"
    else:
        content += "_none_\n"

    content += "\n## Health checks\n"
    for c in health_checks:
        symbol = "✅" if c.passed else "❌"
        content += f"- {symbol} **{c.name}**: {c.message}\n"

    content += "\n## Notes\n\n"

    # Save dated file
    dated_path = CHECKPOINT_DIR / f"{date}.md"
    dated_path.write_text(content)

    # Overwrite CURRENT.md
    current_path = CHECKPOINT_DIR / "CURRENT.md"
    current_path.write_text(content)

    return dated_path


def read_current_checkpoint() -> str:
    """Return the current checkpoint content if it exists."""
    current_path = CHECKPOINT_DIR / "CURRENT.md"
    if current_path.exists():
        return current_path.read_text()
    return "No checkpoint yet."


def list_checkpoints(limit: int = 10) -> list[Path]:
    """Return recent checkpoint files."""
    ensure_checkpoint_dir()
    files = sorted(CHECKPOINT_DIR.glob("*.md"), reverse=True)
    return [f for f in files if f.name != "CURRENT.md"][:limit]


if __name__ == "__main__":
    from pipeline.invariants import HealthCheck
    path = write_daily_checkpoint(
        collected=35,
        worthy=12,
        drafted=3,
        newsletter_sections=5,
        verified=2,
        rejected=1,
        source_errors=["Reuters Tech: 401 blocked"],
        health_checks=[
            HealthCheck(name="sources_csv_exists", passed=True, message="found"),
            HealthCheck(name="worthy_items_have_topics", passed=False, message="3 items lack topics"),
        ],
    )
    print(f"Wrote: {path}")
    print(read_current_checkpoint()[:500])
