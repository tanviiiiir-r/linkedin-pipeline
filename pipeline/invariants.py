"""Pipeline health invariants — lightweight checks that catch silent breakage.

Each invariant returns a HealthCheck with pass/fail status and a human-readable
message. The daily run calls these and reports failures without halting.
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from config.settings import DATA_DIR, SOURCES_CSV
from pipeline.storage import list_items


class HealthCheck(BaseModel):
    name: str
    passed: bool
    message: str
    value: Optional[str] = None


_INVARIANTS: list[dict] = [
    {
        "name": "sources_csv_exists",
        "description": "sources.csv exists and is readable",
    },
    {
        "name": "daily_run_produced_items_or_explained",
        "description": "Daily collection collected >0 new items OR sources had errors explaining why",
    },
    {
        "name": "worthy_items_have_topics",
        "description": "Every worthy item has at least one taxonomy topic",
    },
    {
        "name": "no_leaked_scoring_text_in_drafts",
        "description": "Queued drafts do not contain internal scoring language",
    },
    {
        "name": "queue_dir_exists",
        "description": "Approval queue directory exists",
    },
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def check_sources_csv_exists() -> HealthCheck:
    if SOURCES_CSV.exists():
        return HealthCheck(name="sources_csv_exists", passed=True, message="sources.csv found", value=str(SOURCES_CSV))
    return HealthCheck(name="sources_csv_exists", passed=False, message="sources.csv missing", value=str(SOURCES_CSV))


def check_daily_run_produced_items_or_explained(collected: int, source_errors: list[str]) -> HealthCheck:
    if collected > 0:
        return HealthCheck(
            name="daily_run_produced_items_or_explained",
            passed=True,
            message=f"Collected {collected} new items",
            value=str(collected),
        )
    if source_errors:
        return HealthCheck(
            name="daily_run_produced_items_or_explained",
            passed=True,
            message=f"0 new items but {len(source_errors)} source errors recorded",
            value=str(len(source_errors)),
        )
    return HealthCheck(
        name="daily_run_produced_items_or_explained",
        passed=False,
        message="0 new items and no source errors recorded — possible silent failure",
        value="0",
    )


def check_worthy_items_have_topics() -> HealthCheck:
    items = list_items(status="worthy", limit=1000)
    without_topics = [i for i in items if not getattr(i, "topics", [])]
    if not without_topics:
        return HealthCheck(
            name="worthy_items_have_topics",
            passed=True,
            message=f"All {len(items)} worthy items have topics",
            value=str(len(items)),
        )
    return HealthCheck(
        name="worthy_items_have_topics",
        passed=False,
        message=f"{len(without_topics)} worthy items lack topics",
        value=str(len(without_topics)),
    )


def check_no_leaked_scoring_text_in_drafts() -> HealthCheck:
    queue_dir = DATA_DIR / "queue"
    if not queue_dir.exists():
        return HealthCheck(name="no_leaked_scoring_text_in_drafts", passed=True, message="No queue yet", value="0")

    leaks = ["matched pillar", "pillar_confidence", "signal_strength", "score_item"]
    bad_files = []
    for path in queue_dir.glob("*.md"):
        text = path.read_text(errors="replace").lower()
        if any(leak in text for leak in leaks):
            bad_files.append(path.name)

    if not bad_files:
        return HealthCheck(
            name="no_leaked_scoring_text_in_drafts",
            passed=True,
            message="No scoring text leaked in queued drafts",
            value="0",
        )
    return HealthCheck(
        name="no_leaked_scoring_text_in_drafts",
        passed=False,
        message=f"{len(bad_files)} queued drafts contain leaked scoring text",
        value=str(len(bad_files)),
    )


def check_queue_dir_exists() -> HealthCheck:
    queue_dir = DATA_DIR / "queue"
    if queue_dir.exists():
        return HealthCheck(name="queue_dir_exists", passed=True, message="Queue directory exists", value=str(queue_dir))
    return HealthCheck(name="queue_dir_exists", passed=False, message="Queue directory missing", value=str(queue_dir))


def run_health_checks(collected: int = 0, source_errors: list[str] | None = None) -> list[HealthCheck]:
    """Run all pipeline health invariants and return results."""
    source_errors = source_errors or []
    return [
        check_sources_csv_exists(),
        check_daily_run_produced_items_or_explained(collected, source_errors),
        check_worthy_items_have_topics(),
        check_no_leaked_scoring_text_in_drafts(),
        check_queue_dir_exists(),
    ]


def format_health_report(checks: list[HealthCheck]) -> str:
    lines = ["Pipeline Health Report", "=" * 40]
    for c in checks:
        symbol = "✅" if c.passed else "❌"
        lines.append(f"{symbol} {c.name}: {c.message}")
        if c.value:
            lines.append(f"   value: {c.value}")
    failed = [c for c in checks if not c.passed]
    lines.append(f"\n{len(failed)} failed, {len(checks) - len(failed)} passed")
    return "\n".join(lines)


if __name__ == "__main__":
    checks = run_health_checks(collected=12, source_errors=[])
    print(format_health_report(checks))
