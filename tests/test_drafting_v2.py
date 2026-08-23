"""Tests for pipeline.drafting_v2 LLM humanizer."""
from datetime import date

from config.calendar import day_plan
from pipeline.drafting import Draft
from pipeline.drafting_v2 import _hydrate_draft, _safe_json, _strip_code_fences, draft_item_v2
from pipeline.scoring import ScoreResult
from pipeline.storage import Item


def _item(title: str = "Test Post", summary: str = "A summary.") -> Item:
    return Item(
        source_name="Test Source",
        source_url="https://example.com/feed",
        item_url="https://example.com/post-1",
        item_title=title,
        source_type="rss",
        content_type="article",
        summary=summary,
        key_claims=["claim one", "claim two"],
        raw_content="raw content here",
    )


def _score(pillar: str = "tomorrow_in_ai") -> ScoreResult:
    return ScoreResult(
        pillar=pillar,
        pillar_confidence=70,
        signal_strength=60,
        reason="Test reason",
        topics=["ai builders", "future of ai"],
        primary_topic="future of ai",
    )


def test_strip_code_fences():
    raw = """```json
{"a": 1}
```"""
    assert _strip_code_fences(raw) == '{"a": 1}'


def test_safe_json_tolerates_preamble():
    raw = """Here is your JSON:
{"linkedin_post": "hello"}"""
    data = _safe_json(raw)
    assert data["linkedin_post"] == "hello"
def test_hydrate_draft_returns_draft():
    item = _item()
    score = _score()
    plan = day_plan(date(2026, 8, 23))  # Sunday
    data = {
        "linkedin_post": "Sunday synthesis post.",
        "newsletter_section": "Weekly wrap.",
        "short_pill": "Short.",
        "forward_pill": "Forward.",
        "narrative_pill": "Narrative.",
        "hashtags": ["#AI", "#FutureOfAI"],
    }
    draft = _hydrate_draft(item, score, data, plan)
    assert isinstance(draft, Draft)
    assert draft.pillar == plan.post_type
    assert draft.linkedin_post == "Sunday synthesis post."
    assert draft.hashtags == ["#AI", "#FutureOfAI"]


def test_hydrate_draft_string_hashtags():
    item = _item()
    score = _score()
    plan = day_plan(date(2026, 8, 23))
    data = {
        "linkedin_post": "Post.",
        "newsletter_section": "",
        "short_pill": "",
        "forward_pill": "",
        "narrative_pill": "",
        "hashtags": "#AI, #FutureOfAI",
    }
    draft = _hydrate_draft(item, score, data, plan)
    assert draft.hashtags == ["#AI", "#FutureOfAI"]


def test_draft_item_v2_fallback_on_llm_unavailable(monkeypatch):
    """If is_available returns False, fallback to rule-based draft."""
    monkeypatch.setattr("pipeline.drafting_v2.is_available", lambda: False)
    draft = draft_item_v2(_item(), _score(), day_plan=day_plan(date(2026, 8, 23)))
    assert isinstance(draft, Draft)
    assert draft.linkedin_post != ""


def test_founder_signal_ends_with_question():
    item = _item(title="AI startup wedge", summary="A new pricing wedge changes the game for AI startups.")
    score = _score(pillar="founder_signal")
    plan = day_plan(date(2026, 8, 29))  # Saturday
    data = {
        "linkedin_post": "This pricing wedge is the real moat move.",
        "newsletter_section": "",
        "short_pill": "",
        "forward_pill": "",
        "narrative_pill": "",
        "hashtags": ["#FounderSignal"],
    }
    draft = _hydrate_draft(item, score, data, plan)
    assert draft.linkedin_post.endswith("?")
