import sys
from pathlib import Path

repo = Path(__file__).resolve().parent.parent
if str(repo) not in sys.path:
    sys.path.insert(0, str(repo))

from pipeline.scoring import score_item, is_worthy
from pipeline.storage import Item


def test_score_tool_drop():
    item = Item(
        source_name="Product Hunt AI",
        source_url="https://example.com",
        item_url="https://example.com/tool",
        item_title="New AI tool launched for builders",
        source_type="rss",
        content_type="product",
        summary="A new AI API and framework released today.",
        key_claims=["released a new API"],
    )
    result = score_item(item)
    assert result.pillar == "tool_drop"
    assert result.pillar_confidence > 0
    assert is_worthy(item, min_confidence=50, min_signal=20)


def test_score_no_pillar():
    item = Item(
        source_name="Random",
        source_url="https://example.com",
        item_url="https://example.com/x",
        item_title="Lunch menu",
        source_type="rss",
        content_type="article",
        summary="Today's lunch options.",
        key_claims=[],
    )
    result = score_item(item)
    assert result.pillar is None
    assert not is_worthy(item)


if __name__ == "__main__":
    test_score_tool_drop()
    test_score_no_pillar()
    print("scoring tests passed")
