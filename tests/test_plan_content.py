"""Tests for the plan-content CLI command and planned item lifecycle."""
from datetime import date, datetime, timedelta, timezone

from pipeline.calendar import select_for_today
from pipeline.scoring import score_item
from pipeline.storage import Item, load_planned_items, save_planned_item


def _planned_item(title: str, summary: str, raw: str = "") -> Item:
    return Item(
        source_name="manual",
        source_url="https://example.com/manual",
        item_url=f"https://example.com/manual/{title.lower().replace(chr(32), chr(45))[:40]}",
        item_title=title,
        source_type="manual",
        content_type="article",
        summary=summary,
        raw_content=raw,
        queue_type="planned",
        expires_at=(datetime.now(timezone.utc) + timedelta(days=14)).isoformat(),
        published_at=datetime.now(timezone.utc).isoformat(),
    )


def test_planned_item_saved_and_loaded():
    item = _planned_item("Cursor rules for agentic teams", "How to write .cursorrules files.")
    save_planned_item(item)
    loaded = load_planned_items(limit=100)
    assert any(i.item_title == item.item_title for i in loaded)


def test_planned_item_matches_target_day():
    item = _planned_item(
        "Cursor rules for agentic teams",
        "How to write .cursorrules files that keep multi-agent projects consistent. build deploy cost performance",
    )
    save_planned_item(item)
    selected, note = select_for_today([], limit=1, for_date=date(2026, 8, 27))
    assert note == "planned evergreen"
    assert selected[0][0].item_title == item.item_title
    assert score_item(selected[0][0]).pillar == "builder_memo"


def test_no_planned_item_returns_no_strong_signal():
    # Ensure no matching planned item for a far-future date
    selected, note = select_for_today([], limit=1, for_date=date(2030, 1, 1))
    assert selected == []
    assert note == "no_strong_signal"
