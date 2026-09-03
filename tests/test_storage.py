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


def test_item_from_row_parses_image_candidates():
    from pipeline.storage import _item_from_row
    class FakeRow:
        def __init__(self, d): self.d = d
        def __getitem__(self, k): return self.d[k]
        def keys(self): return list(self.d.keys())
    row = FakeRow({
        'id': 'x', 'source_name': 's', 'source_url': 'u', 'item_url': 'u', 'item_title': 't',
        'item_author': '', 'published_at': '', 'collected_at': 'now', 'source_type': 'rss',
        'content_type': 'article', 'summary': '', 'key_claims': '[]', 'raw_content': '',
        'pillar_candidates': '[]', 'topics': '[]', 'status': 'raw', 'signal_strength': 'auto',
        'url_hash': 'x', 'image_path': '', 'queue_type': 'breaking', 'expires_at': None,
        'engagement': None, 'image_source': '', 'image_candidates': '["a.jpg"]',
    })
    item = _item_from_row(row)
    assert isinstance(item.image_candidates, list)
    assert item.image_candidates == ['a.jpg']
