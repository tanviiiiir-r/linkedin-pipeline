"""Supabase PostgreSQL storage backend for collected items.

Mirrors the interface in pipeline/storage.py. Falls back to SQLite if
SUPABASE_URL/SERVICE_ROLE_KEY are not configured.
"""
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from config.settings import (
    RAW_DIR,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
    ensure_dirs,
)

logger = logging.getLogger(__name__)


def _supabase_client():
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return None
    try:
        from supabase import create_client

        return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    except (ImportError, ConnectionError) as e:
        logger.warning("Supabase init error: %s", e)
        return None


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:12]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SupabaseStorage:
    """PostgreSQL-backed item store with optional local markdown mirror."""

    TABLE = "pipeline_items"

    def __init__(self, client=None):
        self.client = client or _supabase_client()

    def is_available(self) -> bool:
        return self.client is not None

    def init_db(self) -> None:
        """Ensure the items table exists."""
        if not self.client:
            return
        # PostgreSQL JSONB table; create via a no-op upsert that fails if table missing,
        # then fallback to raw REST call for DDL if needed. For now assume table was
        # created via migration/SQL editor ahead of time, or rely on first upsert.
        try:
            self.client.table(self.TABLE).select("id").limit(1).execute()
        except ConnectionError:
            logger.debug("Supabase table check failed; assuming table exists or will be created")

    @staticmethod
    def _item_to_row(item: BaseModel) -> dict:
        data = item.model_dump() if hasattr(item, "model_dump") else item.dict()
        row = dict(data)
        row["key_claims"] = json.dumps(row.get("key_claims", []))
        row["pillar_candidates"] = json.dumps(row.get("pillar_candidates", []))
        row["topics"] = json.dumps(row.get("topics", []))
        # Put extra fields under metadata if the table expects it
        metadata = {}
        for key in list(row.keys()):
            if key not in {
                "id",
                "source_name",
                "source_url",
                "item_url",
                "item_title",
                "item_author",
                "published_at",
                "collected_at",
                "source_type",
                "content_type",
                "summary",
                "key_claims",
                "raw_content",
                "pillar_candidates",
                "topics",
                "status",
                "signal_strength",
                "url_hash",
                "metadata",
            }:
                metadata[key] = row.pop(key)
        row["metadata"] = json.dumps(metadata)
        return row

    def save_item(self, item: BaseModel) -> Path:
        if not self.client:
            raise RuntimeError("Supabase client not available")
        row = self._item_to_row(item)
        self.client.table(self.TABLE).upsert(row, ignore_duplicates=True).execute()

        # Also save a markdown mirror in data/raw for portability
        ensure_dirs()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        source_slug = _slugify(item.source_name)
        out_dir = RAW_DIR / today / source_slug
        out_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).strftime("%H%M%S")
        filename = f"{ts}--{item.id}--{_slugify(item.item_title)}.md"
        path = out_dir / filename
        path.write_text(_markdown_mirror(item))
        return path

    def item_exists(self, url: str) -> bool:
        if not self.client:
            return False
        h = url_hash(url)
        resp = (
            self.client.table(self.TABLE)
            .select("id")
            .or_(f"item_url.eq.{url},url_hash.eq.{h}")
            .execute()
        )
        return bool(resp.data)

    def load_item(self, url: str) -> dict | None:
        if not self.client:
            return None
        h = url_hash(url)
        resp = (
            self.client.table(self.TABLE)
            .select("*")
            .or_(f"item_url.eq.{url},url_hash.eq.{h}")
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

    def list_items(self, status: str | None = None, limit: int = 100) -> list[dict]:
        if not self.client:
            return []
        q = self.client.table(self.TABLE).select("*").order("collected_at", desc=True)
        if status:
            q = q.eq("status", status)
        resp = q.limit(limit).execute()
        return resp.data or []

    def update_status(self, url: str, status: str) -> None:
        if not self.client:
            return
        h = url_hash(url)
        self.client.table(self.TABLE).update({"status": status}).or_(
            f"item_url.eq.{url},url_hash.eq.{h}"
        ).execute()


def _slugify(text: str, max_len: int = 60) -> str:
    import re

    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[-\s]+", "-", text)
    return text[:max_len]


def _markdown_mirror(item: BaseModel) -> str:
    data = item.model_dump() if hasattr(item, "model_dump") else item.dict()
    claims = data.get("key_claims", [])
    claims_md = "\n".join(f"- {c}" for c in claims) if claims else "- [No claims extracted]"
    return f"""---
{json.dumps(data, indent=2, default=str)}
---

## Claims
{claims_md}

## Links
- Primary source: {data.get("item_url", "")}
- Feed source: {data.get("source_url", "")}

## Raw Content
{data.get("raw_content", "")}
"""


def get_storage():
    """Return a SupabaseStorage if configured, otherwise None (caller falls back to SQLite)."""
    s = SupabaseStorage()
    return s if s.is_available() else None
