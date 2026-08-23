"""SQLite + markdown persistence for collected items."""
import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from config.settings import DB_PATH, RAW_DIR, ensure_dirs

logger = logging.getLogger(__name__)

# Optional Supabase PostgreSQL backend
try:
    from pipeline.storage_supabase import SupabaseStorage
    from pipeline.storage_supabase import get_storage as _get_supabase_storage
except ImportError:
    _get_supabase_storage = lambda: None
    logger.debug("Supabase backend not available")


class Item(BaseModel):
    id: str = ""
    source_name: str
    source_url: str
    item_url: str
    item_title: str
    item_author: str = ""
    published_at: str = ""
    collected_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_type: str
    content_type: str = "article"
    summary: str = ""
    key_claims: list[str] = Field(default_factory=list)
    raw_content: str = ""
    pillar_candidates: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    status: str = "raw"
    signal_strength: str = "auto"
    url_hash: str = ""
    reddit_score: int = 0
    reddit_comments: int = 0
    reddit_permalink: str = ""

    model_config = {"extra": "ignore"}

    def model_post_init(self, __context, /):
        if not self.url_hash:
            self.url_hash = url_hash(self.item_url)
        if not self.id:
            self.id = self.url_hash


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:12]


_ALLOWED_INDEX_COLUMNS = {"collected_at", "status", "source_name"}


def _connection() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = _connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY,
            source_name TEXT NOT NULL,
            source_url TEXT NOT NULL,
            item_url TEXT NOT NULL UNIQUE,
            item_title TEXT NOT NULL,
            item_author TEXT,
            published_at TEXT,
            collected_at TEXT NOT NULL,
            source_type TEXT NOT NULL,
            content_type TEXT,
            summary TEXT,
            key_claims TEXT,
            raw_content TEXT,
            pillar_candidates TEXT,
            topics TEXT,
            status TEXT DEFAULT 'raw',
            signal_strength TEXT,
            url_hash TEXT NOT NULL
        )
        """
    )
    for idx in _ALLOWED_INDEX_COLUMNS:
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_items_{idx} ON items({idx})")
    conn.commit()
    conn.close()


def _supabase_storage() -> Optional["SupabaseStorage"]:
    try:
        s = _get_supabase_storage()
        if s and s.is_available():
            return s
    except Exception:
        logger.exception("Supabase backend unavailable")
    return None


def item_exists(url: str) -> bool:
    sb = _supabase_storage()
    if sb:
        return sb.item_exists(url)
    h = url_hash(url)
    conn = _connection()
    cur = conn.execute("SELECT 1 FROM items WHERE item_url = ? OR url_hash = ?", (url, h))
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def save_item(item: Item) -> Path:
    """Persist item to Supabase (if configured) and local markdown/SQLite."""
    if item_exists(item.item_url):
        logger.debug("Skipping save for existing item: %s", item.item_url)
        # Mirror would have been written at original save time; return a stable path.
        today = item.collected_at[:10] if item.collected_at else datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return RAW_DIR / today / _slugify(item.source_name) / f"{item.id}--{_slugify(item.item_title)}.md"
    sb = _supabase_storage()
    if sb:
        return sb.save_item(item)
    ensure_dirs()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    source_slug = _slugify(item.source_name)
    out_dir = RAW_DIR / today / source_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%H%M%S")
    filename = f"{ts}--{item.id}--{_slugify(item.item_title)}.md"
    path = out_dir / filename

    frontmatter = {
        "id": item.id,
        "source_name": item.source_name,
        "source_url": item.source_url,
        "item_url": item.item_url,
        "item_title": item.item_title,
        "item_author": item.item_author,
        "published_at": item.published_at,
        "collected_at": item.collected_at,
        "source_type": item.source_type,
        "content_type": item.content_type,
        "status": item.status,
        "signal_strength": item.signal_strength,
        "url_hash": item.url_hash,
        "pillar_candidates": item.pillar_candidates,
        "topics": item.topics,
    }

    md = f"""---
{json.dumps(frontmatter, indent=2)}
---

## Claims
{chr(10).join(f"- {c}" for c in item.key_claims) or "- [No claims extracted]"}

## Links
- Primary source: {item.item_url}
- Feed source: {item.source_url}

## Raw Content
{item.raw_content}
"""
    path.write_text(md)

    conn = _connection()
    conn.execute(
        """
        INSERT INTO items (id, source_name, source_url, item_url, item_title, item_author,
            published_at, collected_at, source_type, content_type, summary, key_claims,
            raw_content, pillar_candidates, topics, status, signal_strength, url_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(item_url) DO UPDATE SET
            collected_at=excluded.collected_at,
            status=excluded.status,
            summary=excluded.summary,
            key_claims=excluded.key_claims,
            raw_content=excluded.raw_content
        """,
        (
            item.id, item.source_name, item.source_url, item.item_url, item.item_title,
            item.item_author, item.published_at, item.collected_at, item.source_type,
            item.content_type, item.summary, json.dumps(item.key_claims), item.raw_content,
            json.dumps(item.pillar_candidates), json.dumps(item.topics), item.status,
            item.signal_strength, item.url_hash,
        ),
    )
    conn.commit()
    conn.close()
    return path


def load_item(url: str) -> Item | None:
    sb = _supabase_storage()
    if sb:
        row = sb.load_item(url)
        if row:
            return _item_from_row(row)
    h = url_hash(url)
    conn = _connection()
    row = conn.execute(
        "SELECT * FROM items WHERE item_url = ? OR url_hash = ?", (url, h)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return _item_from_row(row)


def list_items(status: str | None = None, limit: int = 100) -> list[Item]:
    sb = _supabase_storage()
    if sb:
        rows = sb.list_items(status=status, limit=limit)
        return [_item_from_row({k: row.get(k) for k in row}) for row in rows]
    conn = _connection()
    if status:
        rows = conn.execute(
            "SELECT * FROM items WHERE status = ? ORDER BY collected_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM items ORDER BY collected_at DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [_item_from_row(row) for row in rows]


def update_status(url: str, status: str) -> None:
    sb = _supabase_storage()
    if sb:
        sb.update_status(url, status)
        return
    conn = _connection()
    conn.execute(
        "UPDATE items SET status = ? WHERE item_url = ? OR url_hash = ?",
        (status, url, url_hash(url)),
    )
    conn.commit()
    conn.close()


def _slugify(text: str, max_len: int = 60) -> str:
    import re
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[-\s]+", "-", text)
    return text[:max_len]


def _item_from_row(row) -> Item:
    data: dict = {}
    keys = row.keys() if hasattr(row, "keys") else list(range(len(row)))
    for key in keys:
        value = row[key]
        if value is None:
            data[key] = [] if key in ("key_claims", "pillar_candidates", "topics") else "" if key in ("reddit_permalink",) else 0 if key in ("reddit_score", "reddit_comments") else value
            continue
        if key in ("key_claims", "pillar_candidates", "topics"):
            try:
                data[key] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                data[key] = []
        elif key in ("reddit_score", "reddit_comments"):
            try:
                data[key] = int(value)
            except (ValueError, TypeError):
                data[key] = 0
        else:
            data[key] = value
    return Item(**data)


def _json_loads(key: str, value):
    if value is None:
        return []
    if key in ("key_claims", "pillar_candidates", "topics"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return []
    return value
