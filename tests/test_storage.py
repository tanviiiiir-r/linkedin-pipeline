import sys
from pathlib import Path

repo = Path(__file__).resolve().parent.parent
if str(repo) not in sys.path:
    sys.path.insert(0, str(repo))

import os
os.environ["DATA_DIR"] = str(repo / "test_data")

from pipeline.storage import Item, init_db, item_exists, save_item, load_item, list_items


def test_save_and_load():
    init_db()
    item = Item(
        source_name="Test Source",
        source_url="https://example.com/feed",
        item_url="https://example.com/post-1",
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
