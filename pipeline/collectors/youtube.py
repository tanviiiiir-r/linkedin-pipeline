"""YouTube collector using Composio's connected YouTube app.

Collects recent videos from a curated list of AI/security/infrastructure channels
and stores them as Items.
"""
import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Optional

from pipeline.storage import Item, item_exists, save_item

YOUTUBE_CHANNELS = [
    ("Andrej Karpathy", "@AndrejKarpathy"),
    ("AI Explained", "@aiexplained-official"),
    ("Two Minute Papers", "@TwoMinutePapers"),
    ("Yannic Kilcher", "@YannicKilcher"),
]


def _run(slug: str, payload: dict) -> dict:
    env = {**os.environ, "PATH": "/opt/data/home/.local/bin:" + os.environ.get("PATH", "")}
    proc = subprocess.run(
        ["composio", "execute", slug, "-d", json.dumps(payload)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Composio {slug} failed: {proc.stderr}")
    if not proc.stdout.strip():
        raise RuntimeError(f"Composio {slug} returned empty stdout")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Composio {slug} returned invalid JSON: {e}")


def _get_channel_id(handle: str) -> Optional[str]:
    data = _run("YOUTUBE_GET_CHANNEL_ID_BY_HANDLE", {"channel_handle": handle})
    items = data.get("data", {}).get("items", [])
    if items:
        return items[0].get("id")
    return None


def _parse_iso8601(ts: str) -> str:
    """Convert YouTube publishedAt to ISO datetime string."""
    ts = ts.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(ts)
        return dt.isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def _video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _normalize_channel(channel_name: str, handle: str, limit: int = 3) -> list[Item]:
    channel_id = _get_channel_id(handle)
    if not channel_id:
        print(f"  could not resolve channel {handle}")
        return []

    data = _run(
        "YOUTUBE_LIST_CHANNEL_VIDEOS",
        {"channelId": channel_id, "maxResults": limit},
    )

    items: list[Item] = []
    for entry in data.get("data", {}).get("items", []):
        snippet = entry.get("snippet", {})
        title = snippet.get("title", "Untitled")
        published = snippet.get("publishedAt", "")
        description = snippet.get("description", "")
        video_id = snippet.get("resourceId", {}).get("videoId", "")
        if not video_id:
            continue
        video_url = _video_url(video_id)
        if item_exists(video_url):
            continue

        raw = f"{title}\n\n{description}"[:3000]
        item = Item(
            source_name=f"YouTube {channel_name}",
            source_url=f"https://www.youtube.com/{handle}",
            item_url=video_url,
            item_title=title,
            published_at=_parse_iso8601(published) if published else datetime.now(timezone.utc).isoformat(),
            source_type="youtube",
            content_type="video",
            summary=description[:500],
            key_claims=[description[:240]],
            raw_content=raw,
        )
        items.append(item)
    return items


def collect_youtube(
    dry_run: bool = False,
    limit_per_channel: int = 3,
    channels: Optional[list[tuple[str, str]]] = None,
) -> int:
    channels = channels or YOUTUBE_CHANNELS
    total = 0
    for channel_name, handle in channels:
        print(f"[YouTube {channel_name}] {handle}")
        items = _normalize_channel(channel_name, handle, limit=limit_per_channel)
        print(f"  fetched {len(items)} new")
        if not dry_run:
            for item in items:
                save_item(item)
        total += len(items)
    return total


if __name__ == "__main__":
    print(f"YouTube collection complete: {collect_youtube(dry_run=True, limit_per_channel=2)} new items")
