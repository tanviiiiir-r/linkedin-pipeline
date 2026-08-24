"""Tests for claim verification in pipeline.verify."""
from datetime import datetime, timezone

from pipeline.drafting import Draft
from pipeline.storage import Item
from pipeline.verify import (
    _claim_source_overlap,
    _extract_claims_from_draft,
    _number_tolerated,
    _verify_claims,
    verify_draft,
)


def _make_item(raw: str, title: str = "Source Title", summary: str = "") -> Item:
    return Item(
        source_name="Test Source",
        source_url="https://example.com/feed",
        item_url="https://example.com/post-123",
        item_title=title,
        source_type="rss",
        content_type="article",
        summary=summary,
        raw_content=raw,
    )


def _make_draft(post: str, source_url: str = "https://example.com/post-123") -> Draft:
    return Draft(
        item_id="abc123",
        pillar="builder_memo",
        title="Test Draft",
        source_url=source_url,
        created_at=datetime.now(timezone.utc).isoformat(),
        linkedin_post=post,
        newsletter_section="",
        hashtags=["#BuilderMemo", "#SecureAI"],
    )


def test_extract_claims_finds_numbers_and_assertions():
    text = "Pinterest reported a 12% lift in WAU. Their system uses 3 clusters. This is a big shift."
    claims = _extract_claims_from_draft(text)
    assert any("12%" in c for c in claims)
    assert any("Pinterest" in c for c in claims)


def test_claim_source_overlap_high_for_matching_claims():
    item = _make_item("Pinterest reported a 12% lift in WAU by modeling user lifecycles.")
    overlap = _claim_source_overlap("Pinterest reported a 12% lift in WAU.", f"{item.item_title} {item.summary} {item.raw_content}")
    assert overlap >= 0.5


def test_claim_source_overlap_low_for_unrelated_claims():
    item = _make_item("A new CLI tool for LLMs was released today.")
    overlap = _claim_source_overlap("OpenAI reported a 50% revenue increase.", f"{item.item_title} {item.summary} {item.raw_content}")
    assert overlap < 0.5


def test_number_tolerated_allows_small_counts_and_years():
    assert _number_tolerated("3", "any source") is True
    assert _number_tolerated("2026", "any source") is True
    assert _number_tolerated("999", "any source") is False


def test_verify_claims_passes_when_claims_match_source():
    item = _make_item("Pinterest's Pinner Progression lifted WAU by modeling user lifecycles.")
    draft = _make_draft("Pinterest's Pinner Progression lifted WAU by modeling user lifecycles.")
    checks = _verify_claims(draft, item)
    assert checks["claims_source_match"] is True
    assert checks["no_hallucinated_numbers"] is True


def test_verify_claims_fails_on_hallucinated_number():
    item = _make_item("Pinterest's Pinner Progression lifted WAU.")
    draft = _make_draft("Pinterest reported a 94% lift in WAU.")
    checks = _verify_claims(draft, item)
    assert checks["no_hallucinated_numbers"] is False


def test_verify_draft_penalizes_hallucinated_claim():
    from pipeline.storage import init_db
    init_db()  # Ensure items table exists for load_item inside verify_draft
    draft = _make_draft("Pinterest reported a 94% lift in WAU.")
    result = verify_draft(draft)
    assert result.checks["no_hallucinated_numbers"] is False
    assert result.score < 80


def test_verify_draft_approves_when_claims_match():
    item = _make_item("Pinterest's Pinner Progression lifted WAU by modeling user lifecycles.")
    draft = _make_draft("Pinterest's Pinner Progression lifted WAU by modeling user lifecycles. Read more: https://example.com/post-123")
    # Save the item so load_item finds it
    from pipeline.storage import init_db, save_item
    init_db()
    save_item(item)
    result = verify_draft(draft)
    assert result.checks["claims_source_match"] is True
    assert result.checks["no_hallucinated_numbers"] is True
