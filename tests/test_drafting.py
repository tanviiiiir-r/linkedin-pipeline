import sys
from pathlib import Path

repo = Path(__file__).resolve().parent.parent
if str(repo) not in sys.path:
    sys.path.insert(0, str(repo))

from pipeline.drafting import draft_item, save_draft
from pipeline.scoring import ScoreResult
from pipeline.storage import Item


def test_draft_shape():
    item = Item(
        source_name="Hacker News",
        source_url="https://news.ycombinator.com/rss",
        item_url="https://example.com/post",
        item_title="New MCP roadmap released",
        source_type="rss",
        content_type="article",
        summary="A new roadmap for MCP.",
        key_claims=["MCP roadmap released"],
        topics=["mcp", "agents"],
    )
    score = ScoreResult(pillar="tool_drop", pillar_confidence=75, signal_strength=60)
    draft = draft_item(item, score)
    assert "New MCP roadmap released" in draft.linkedin_post
    assert "#AI" in draft.hashtags
    assert draft.newsletter_section


def test_save_draft(tmp_path):
    draft = draft_item(Item(
        source_name="HN",
        source_url="https://news.ycombinator.com/rss",
        item_url="https://example.com/post",
        item_title="AI agents trending",
        source_type="rss",
        content_type="article",
        summary="Agents are taking over.",
        key_claims=["agent trend"],
    ), ScoreResult(pillar="viral_explained", pillar_confidence=60, signal_strength=55))
    path = save_draft(draft, tmp_path)
    assert path.exists()
    assert "LinkedIn Post" in path.read_text()


if __name__ == "__main__":
    from pathlib import Path
    test_draft_shape()
    test_save_draft(Path(__file__).resolve().parent.parent / "test_data" / "queue")
    print("drafting tests passed")
