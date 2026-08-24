"""Tests for pipeline.freshness recency gating."""
from datetime import datetime, timedelta, timezone

from pipeline.freshness import (
    age_penalty_score,
    engagement_score,
    format_age,
    is_fresh_breaking,
    item_age_hours,
    passes_recency_gate,
    planned_decay_score,
)
from pipeline.storage import Item


def _item(source_type: str, hours_old: float, engagement: dict | None = None, title: str = "Title") -> Item:
    return Item(
        source_name="Test",
        source_url="https://example.com/feed",
        item_url="https://example.com/item",
        item_title=title,
        source_type=source_type,
        content_type="article",
        summary="summary",
        published_at=(datetime.now(timezone.utc) - timedelta(hours=hours_old)).isoformat(),
        engagement=engagement or {},
    )


def test_item_age_hours():
    i = _item("rss", 12)
    assert 11.9 < item_age_hours(i) < 12.1


def test_fresh_rss_passes():
    i = _item("rss", 12)
    ok, reason = passes_recency_gate(i)
    assert ok
    assert reason == ""


def test_stale_rss_rejected():
    i = _item("rss", 80)
    ok, reason = passes_recency_gate(i)
    assert not ok
    assert "older than" in reason


def test_reddit_low_engagement_rejected():
    i = _item("reddit", 12, engagement={"score": 5, "comments": 1})
    ok, reason = passes_recency_gate(i)
    assert not ok
    assert "score" in reason


def test_reddit_high_engagement_passes():
    i = _item("reddit", 12, engagement={"score": 120, "comments": 35})
    ok, _reason = passes_recency_gate(i)
    assert ok
    assert engagement_score(i) > 0


def test_stale_evergreen_demoted():
    i = _item("rss", 72, title="Why MCP changes everything")
    ok, reason = passes_recency_gate(i)
    assert not ok
    assert "stale evergreen" in reason


def test_fresh_evergreen_with_release_allowed():
    i = _item("rss", 12, title="New MCP repo launched")
    ok, _reason = passes_recency_gate(i)
    assert ok


def test_age_penalty_after_grace_period():
    assert age_penalty_score(12) == 0
    assert age_penalty_score(48) < 0
    assert age_penalty_score(72) < age_penalty_score(48)


def test_planned_decay():
    i = Item(
        source_name="Test",
        source_url="s",
        item_url="u",
        item_title="t",
        source_type="manual",
        queue_type="planned",
        published_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        expires_at=(datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
    )
    assert planned_decay_score(i) < 0
    assert planned_decay_score(i) > -50


def test_format_age():
    i = _item("rss", 0.5)
    assert "m" in format_age(i)
    i = _item("rss", 10)
    assert "h" in format_age(i)
    i = _item("rss", 72)
    assert "d" in format_age(i)


def test_is_fresh_breaking():
    assert is_fresh_breaking(_item("rss", 12))
    assert not is_fresh_breaking(_item("rss", 80))
