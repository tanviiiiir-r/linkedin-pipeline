"""Tests for pipeline.calendar day-plan selection."""
from datetime import date, datetime, timedelta, timezone

from config.calendar import day_plan
from pipeline.calendar import select_for_day, select_for_today
from pipeline.scoring import ScoreResult
from pipeline.storage import Item


def _item(
    title: str,
    source_name: str,
    summary: str,
    *,
    hours_old: float = 12,
    engagement: dict | None = None,
    queue_type: str = "breaking",
    **kwargs,
) -> Item:
    return Item(
        source_name=source_name,
        source_url="https://example.com/feed",
        item_url=f"https://example.com/{title.replace(' ', '-')}",
        item_title=title,
        source_type="rss",
        content_type="article",
        summary=summary,
        published_at=(datetime.now(timezone.utc) - timedelta(hours=hours_old)).isoformat(),
        engagement=engagement or {},
        queue_type=queue_type,
        **kwargs,
    )


def test_select_for_tool_drop_prefers_tool_terms():
    plan = day_plan(date(2026, 8, 24))  # Monday
    items = [
        _item("New model paper", "arXiv", "We introduce a transformer architecture."),
        _item("New CLI for LLMs", "GitHub", "A command-line tool that calls OpenAI-compatible APIs."),
    ]
    selected, note = select_for_day(items, plan, limit=1, mode="hybrid")
    assert len(selected) == 1
    assert note.startswith("breaking signal")
    item, _ = selected[0]
    assert "CLI" in item.item_title


def test_select_for_founders_prefers_gtm_signals():
    plan = day_plan(date(2026, 8, 29))  # Saturday
    items = [
        _item("GPU prices fall", "Hacker News", "Nvidia lowers cloud GPU pricing.", engagement={"score": 200, "comments": 60}),
        _item("Why this AI startup won GTM", "TechCrunch", "Their wedge was a pricing model that incumbents couldn't match.", engagement={"score": 400, "comments": 120}),
    ]
    selected, _note = select_for_day(items, plan, limit=1, mode="hybrid")
    assert len(selected) == 1
    item, _ = selected[0]
    assert "startup" in item.item_title.lower() or "wedge" in item.summary.lower()


def test_select_for_today_uses_sunday():
    # Default Sunday plan should produce a breaking result with fresh items.
    items = [_item("Recap of the week", "Interconnects", "What changed in AI this week.")]
    result, note = select_for_today(items, limit=1)
    assert isinstance(result, list)
    assert note in ("breaking signal", "planned evergreen", "no_strong_signal")


def test_score_passed_through():
    plan = day_plan(date(2026, 8, 26))  # Wednesday pattern spotting
    item = _item("Agent orchestration trend", "Hacker News", "Several projects now combine agents with new workflow patterns.")
    selected, _ = select_for_day([item], plan, limit=1)
    assert len(selected) == 1
    _, score = selected[0]
    assert isinstance(score, ScoreResult)


def test_stale_item_rejected_in_breaking_mode():
    plan = day_plan(date(2026, 8, 24))  # Monday
    fresh = _item("Fresh tool", "GitHub", "New CLI released today.", hours_old=12)
    stale = _item("Stale tool", "GitHub", "Old CLI from weeks ago.", hours_old=80)
    selected, note = select_for_day([fresh, stale], plan, limit=1, mode="breaking")
    assert len(selected) == 1
    assert selected[0][0].item_title == "Fresh tool"
    assert note.startswith("breaking signal")


def test_hybrid_falls_back_to_planned():
    plan = day_plan(date(2026, 8, 24))  # Monday
    stale = _item("Stale tool", "GitHub", "Old CLI.", hours_old=80)
    planned = _item(
        "Planned evergreen tool tip",
        "Simon Willison",
        "A practical SQLite trick for AI apps.",
        hours_old=12,
        queue_type="planned",
        expires_at=(datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
    )
    # Seed planned item via storage helper so load_planned_items sees it
    from pipeline.storage import save_planned_item
    save_planned_item(planned)
    selected, note = select_for_day([stale], plan, limit=1, mode="hybrid")
    assert len(selected) == 1
    assert note == "planned evergreen"
    assert selected[0][0].queue_type == "planned"


def test_no_strong_signal_returns_empty():
    plan = day_plan(date(2026, 8, 24))  # Monday
    stale = _item("Stale unrelated", "Random", "Nothing useful.", hours_old=80)
    selected, note = select_for_day([stale], plan, limit=1, mode="breaking", threshold=80)
    assert selected == []
    assert note == "no_strong_signal"


def test_engagement_velocity_bonus():
    plan = day_plan(date(2026, 8, 24))  # Monday
    low = _item("Low buzz tool", "Hacker News", "New tool.", engagement={"score": 2, "comments": 0})
    high = _item("Hot tool", "Hacker News", "New tool.", engagement={"score": 200, "comments": 80})
    selected, _ = select_for_day([low, high], plan, limit=1, mode="hybrid", threshold=25)
    assert selected[0][0].item_title == "Hot tool"
