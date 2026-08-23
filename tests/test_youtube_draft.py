"""Tests for youtube_draft helpers."""

from pipeline.youtube_draft import _video_id, item_from_youtube_url


def test_video_id_standard_url():
    assert _video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_video_id_short():
    assert _video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_video_id_invalid():
    assert _video_id("https://example.com") is None


def test_item_from_youtube_url_creates_item(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # Re-load settings in a fresh process is hard; instead patch config directly.
    from config import settings
    settings.DATA_DIR = tmp_path
    settings.DB_PATH = tmp_path / "content.db"
    settings.RAW_DIR = tmp_path / "raw"
    settings.QUEUE_DIR = tmp_path / "queue"
    settings.ensure_dirs()

    item = item_from_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert item is not None
    assert "dQw4w9WgXcQ" in item.item_url
