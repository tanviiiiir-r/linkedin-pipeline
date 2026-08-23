"""Tests for pipeline.calendar day-plan selection."""
from datetime import date

from config.calendar import day_plan
from pipeline.calendar import select_for_day, select_for_today
from pipeline.scoring import ScoreResult
from pipeline.storage import Item


def _item(title: str, source_name: str, summary: str, **kwargs) -> Item:
    return Item(
        source_name=source_name,
        source_url="https://example.com/feed",
        item_url=f"https://example.com/{title.replace(' ', '-')}",
        item_title=title,
        source_type="rss",
        content_type="article",
        summary=summary,
        **kwargs,
    )


def test_select_for_tool_drop_prefers_tool_terms():
    plan = day_plan(date(2026, 8, 24))  # Monday
    items = [
        _item("New model paper", "arXiv", "We introduce a transformer architecture."),
        _item("New CLI for LLMs", "GitHub", "A command-line tool that calls OpenAI-compatible APIs."),
    ]
    selected = select_for_day(items, plan, limit=1)
    assert len(selected) == 1
    item, _ = selected[0]
    assert "CLI" in item.item_title


def test_select_for_founders_prefers_gtm_signals():
    plan = day_plan(date(2026, 8, 29))  # Saturday
    items = [
        _item("GPU prices fall", "Hacker News", "Nvidia lowers cloud GPU pricing."),
        _item("Why this AI startup won GTM", "TechCrunch", "Their wedge was a pricing model that incumbents couldn't match."),
    ]
    selected = select_for_day(items, plan, limit=1)
    assert len(selected) == 1
    item, _ = selected[0]
    assert "startup" in item.item_title.lower() or "wedge" in item.summary.lower()


def test_select_for_today_uses_sunday():
    # Just check it returns a list without crashing; real date is Sunday 2026-08-23.
    items = [_item("Recap of the week", "Interconnects", "What changed in AI this week.")]
    result = select_for_today(items, limit=1)
    assert isinstance(result, list)


def test_score_passed_through():
    plan = day_plan(date(2026, 8, 26))  # Wednesday pattern spotting
    item = _item("Agent orchestration trend", "Hacker News", "Several projects now combine agents with MCP.")
    selected = select_for_day([item], plan, limit=1)
    _, score = selected[0]
    assert isinstance(score, ScoreResult)
