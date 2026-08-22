"""Instagram collector using Composio's connected Instagram app.

Collects recent posts from a curated list of builder/AI Instagram accounts.
Because Instagram requires a business/creator account id and the API returns
media for the connected account, this collector focuses on the connected user's
own feed as a trend signal. It can be extended to lookup other accounts if the
connected account has the necessary permissions.
"""
import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Optional

from pipeline.storage import Item, item_exists, save_item

INSTAGRAM_ACCOUNTS = [
    # These are handles for reference; the Composio Instagram API operates on
    # the connected user's media. Discovery of other accounts may require
    # additional permissions.
    ("connected_user", "me"),
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


def _get_user_id() -> Optional[str]:
    data = _run("INSTAGRAM_GET_USER_INFO", {})
    return data.get("data", {}).get("id")


def _parse_iso8601(ts: str) -> str:
    if ts.endswith("+0000"):
        ts = ts[:-5] + "+00:00"
    try:
        dt = datetime.fromisoformat(ts)
        return dt.isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def _normalize_media(
    account_name: str, media: dict, since: Optional[int] = None
) -> Optional[Item]:
    media_id = media.get("id", "")
    caption = media.get("caption", "") or ""
    permalink = media.get("permalink", "")
    timestamp = media.get("timestamp", "")
    media_type = media.get("media_type", "")
    thumbnail_url = media.get("thumbnail_url") or media.get("media_url", "")

    if not permalink or item_exists(permalink):
        return None
    if since and timestamp:
        try:
            ts_dt = datetime.fromisoformat(timestamp.replace("+0000", "+00:00"))
            if int(ts_dt.timestamp()) < since:
                return None
        except Exception:
            pass

    return Item(
        source_name=f"Instagram {account_name}",
        source_url=f"https://www.instagram.com/{account_name}/",
        item_url=permalink,
        item_title=caption[:120] or f"Instagram {media_type}",
        published_at=_parse_iso8601(timestamp) if timestamp else datetime.now(timezone.utc).isoformat(),
        source_type="instagram",
        content_type="short",
        summary=caption[:500],
        key_claims=[caption[:240]] if caption else [],
        raw_content=caption[:3000],
    )


def collect_instagram(
    dry_run: bool = False,
    limit: int = 10,
    since: Optional[int] = None,
) -> int:
    print("[Instagram] fetching connected account media")
    user_id = _get_user_id()
    if not user_id:
        print("  could not resolve Instagram user id")
        return 0

    payload = {"ig_user_id": user_id, "limit": limit}
    data = _run("INSTAGRAM_GET_IG_USER_MEDIA", payload)

    total = 0
    for media in data.get("data", {}).get("data", []):
        item = _normalize_media("connected_user", media, since=since)
        if not item:
            continue
        print(f"  {item.item_title[:60]}")
        if not dry_run:
            save_item(item)
        total += 1
    print(f"  {total} new")
    return total


if __name__ == "__main__":
    print(f"Instagram collection complete: {collect_instagram(dry_run=True, limit=5)} new items")
