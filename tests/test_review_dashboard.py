"""Tests for review dashboard and server helpers."""
from pathlib import Path

import pytest

from config.settings import DATA_DIR, QUEUE_DIR, REVIEW_DIR
from pipeline.approval import approve_draft, edit_draft, skip_draft
from pipeline.drafting import Draft, _draft_markdown, save_draft
from pipeline.review_dashboard import generate_dashboard


@pytest.fixture(autouse=True)
def _clean_queue(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings.QUEUE_DIR", tmp_path / "queue")
    monkeypatch.setattr("config.settings.REVIEW_DIR", tmp_path / "review")
    monkeypatch.setattr("config.settings.DATA_DIR", tmp_path)
    (tmp_path / "queue").mkdir(parents=True, exist_ok=True)
    (tmp_path / "review").mkdir(parents=True, exist_ok=True)


def make_draft(item_id: str = "abc123", pillar: str = "tool_drop") -> Draft:
    return Draft(
        item_id=item_id,
        pillar=pillar,
        title="Test Draft",
        source_url="https://example.com/test",
        created_at="2024-01-01T00:00:00Z",
        approved=False,
        published=False,
        linkedin_post="This is a test post.\n\nIt has multiple lines.",
        hashtags=["#AI", "#Test"],
        image_path="",
    )


def test_generate_dashboard_empty():
    path = generate_dashboard()
    assert path.exists()
    text = path.read_text()
    assert "No pending drafts" in text


def test_generate_dashboard_with_draft():
    draft = make_draft()
    save_draft(draft, QUEUE_DIR)
    path = generate_dashboard()
    text = path.read_text()
    assert "Test Draft" in text
    assert "tool_drop" in text
    assert "This is a test post" in text
    assert "#AI" in text


def test_edit_draft():
    draft = make_draft()
    path = save_draft(draft, QUEUE_DIR)
    assert edit_draft(draft.item_id, "Updated post body")
    new_text = path.read_text()
    assert "Updated post body" in new_text
    assert (path.with_suffix(".md.bak")).exists()


def test_skip_draft():
    draft = make_draft()
    path = save_draft(draft, QUEUE_DIR)
    assert skip_draft(draft.item_id)
    assert not path.exists()
    skipped = QUEUE_DIR / "skipped" / path.name
    assert skipped.exists()


def test_approve_draft():
    draft = make_draft()
    path = save_draft(draft, QUEUE_DIR)
    assert approve_draft(draft.item_id)
    new_text = path.read_text()
    assert "approved: True" in new_text
