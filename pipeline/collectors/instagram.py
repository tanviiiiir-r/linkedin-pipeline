"""Instagram collector using Composio's connected Instagram app.

Collects recent posts from a curated list of builder/AI Instagram accounts.
Because Instagram requires a business/creator account id and the API returns
media for the connected account, this collector focuses on the connected user's
own feed as a trend signal. It can be extended to lookup other accounts if the
connected account has the necessary permissions.
"""
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone

from pipeline.storage import Item, item_exists, save_item

logger = logging.getLogger(__name__)

COMPOSIO_SEARCH_PATHS = [
    "/opt/data/home/.local/bin",
    "/opt/data/.local/bin",
    os.path.expanduser("~/.local/bin"),
]

INSTAGRAM_ACCOUNTS = [
    # These are handles for reference; the Composio Instagram API operates on
    # the connected user's media. Discovery of other accounts may require
    # additional permissions.
    ("connected_user", "me"),
]


def _composio_bin() -> str:
    """Resolve the absolute path to the composio CLI, raising if unavailable."""
    candidate = shutil.which("composio")
    if not candidate:
        for d in COMPOSIO_SEARCH_PATHS:
            candidate = shutil.which("composio", path=d)
            if candidate:
                break
    if not candidate:
        raise RuntimeError("composio CLI not found on PATH")
    return candidate


def _run(slug: str, payload: dict) -> dict:
    env = {**os.environ, "PATH": "/opt/data/home/.local/bin:" + os.environ.get("PATH", "")}
    binary = _composio_bin()
    proc = subprocess.run(
        [binary, "execute", slug, "-d", json.dumps(payload)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Composio {slug} failed: {proc.stderr}")
    if not proc.stdout.strip():
        raise RuntimeError(f"Composio {slug} returned empty stdout")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Composio {slug} returned invalid JSON: {e}")


def _get_user_id() -> str | None:
    data = _run("INSTAGRAM_GET_USER_INFO", {})
    return data.get("data", {}).get("id")


def _parse_iso8601(ts: str) -> str:
    if ts.endswith("+0000"):
        ts = ts[:-5] + "+00:00"
    try:
        dt = datetime.fromisoformat(ts)
        return dt.isoformat()
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).isoformat()


def _normalize_media(
    account_name: str, media: dict, since: int | None = None
) -> Item | None:
    caption = media.get("caption", "") or ""
    permalink = media.get("permalink", "")
    timestamp = media.get("timestamp", "")
    media_type = media.get("media_type", "")

    if not permalink or item_exists(permalink):
        return None
    if since and timestamp:
        try:
            ts_dt = datetime.fromisoformat(timestamp.replace("+0000", "+00:00"))
            if int(ts_dt.timestamp()) < since:
                return None
        except (ValueError, OSError):
            logger.warning("Could not parse Instagram timestamp: %s", timestamp)

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
    since: int | None = None,
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
