"""Tests for local item storage.

The conftest sets DATA_DIR to test_data before any imports happen. Tests here
only touch the test database and raw directory.
"""
import uuid

from pipeline.storage import Item, init_db, item_exists, list_items, load_item, save_item


def test_save_and_load():
    init_db()
    unique = uuid.uuid4().hex[:8]
    item = Item(
        source_name="Test Source",
        source_url="https://example.com/feed",
        item_url=f"https://example.com/post-{unique}",
        item_title="Test Post",
        source_type="rss",
        content_type="article",
        summary="A test summary.",
        key_claims=["claim one", "claim two"],
        raw_content="raw content here",
    )
    path = save_item(item)
    assert path.exists()
    loaded = load_item(item.item_url)
    assert loaded is not None
    assert loaded.item_title == "Test Post"
    assert loaded.key_claims == ["claim one", "claim two"]
    assert item_exists(item.item_url)


def test_list_items():
    init_db()
    items = list_items(limit=10)
    assert isinstance(items, list)


if __name__ == "__main__":
    test_save_and_load()
    test_list_items()
    print("storage tests passed")
