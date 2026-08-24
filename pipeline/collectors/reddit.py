"""Reddit collector using Composio's connected Reddit app.

Collects top/hot posts from AI/security/infrastructure subreddits and stores them
as Items in the shared storage backend (Supabase/SQLite).
"""
import hashlib
import json
import logging
import shutil
import subprocess  # nosec B404
from datetime import datetime, timezone

from pipeline.freshness import passes_recency_gate
from pipeline.storage import Item, item_exists, save_item

logger = logging.getLogger(__name__)

COMPOSIO_BIN: str | None = None


def _composio_bin() -> str | None:
    global COMPOSIO_BIN
    if COMPOSIO_BIN is not None:
        return COMPOSIO_BIN
    COMPOSIO_BIN = shutil.which("composio")
    alt = "/opt/data/home/.local/bin/composio"
    if not COMPOSIO_BIN and shutil.which(alt):
        COMPOSIO_BIN = alt
    return COMPOSIO_BIN


def _execute(slug: str, payload: dict) -> dict:
    binary = _composio_bin()
    if not binary:
        raise RuntimeError("composio CLI not found on PATH")
    cmd = [binary, "execute", slug, "-d", json.dumps(payload)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)  # nosec B603
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError:
        return {"ok": False, "error": result.stdout or result.stderr}
    if not data.get("successful", result.returncode == 0):
        return {"ok": False, "error": data.get("error", result.stderr or "unknown error")}
    data["ok"] = True
    return data


REDDIT_COMMUNITIES = {
    "high": {
        "LocalLLaMA": 10,
        "MachineLearning": 10,
        "singularity": 10,
        "artificial": 10,
    },
    "medium": {
        "ai_agents": 5,
        "LLMDevs": 5,
        "LangChain": 5,
        "Rag": 5,
        "Vectordatabase": 5,
        "LocalLLM": 5,
        "datascience": 5,
        "hackernews": 5,
        "cybersecurity": 5,
        "netsec": 5,
    },
}


def _utc_from_timestamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _post_to_item(post: dict, source_name: str) -> Item:
    data = post.get("data", post)
    title = data.get("title", "")
    url = data.get("url", "")
    permalink = data.get("permalink", "")
    item_url = url if url and not url.endswith(('.png', '.jpg', '.jpeg', '.gif')) else f"https://www.reddit.com{permalink}"
    selftext = data.get("selftext", "")
    author = data.get("author", "")
    subreddit = data.get("subreddit", source_name)
    created_utc = data.get("created_utc", 0)
    score = data.get("score", 0)
    num_comments = data.get("num_comments", 0)

    # Extract claims / key lines from selftext
    key_claims = []
    for line in selftext.splitlines():
        line = line.strip()
        if len(line) > 40 and not line.startswith(('#', '>', '- ', '* ', '1.', '2.', '3.')):
            key_claims.append(line[:200])
            if len(key_claims) >= 3:
                break

    raw = selftext or title
    # Truncate long selftexts
    if len(raw) > 4000:
        raw = raw[:4000] + "\n\n[truncated]"

    published = _utc_from_timestamp(created_utc) if created_utc else datetime.now(timezone.utc).isoformat()
    hours_old = (datetime.now(timezone.utc) - datetime.fromisoformat(published)).total_seconds() / 3600.0 if published else 0.0
    velocity = round(score / max(1, hours_old), 2)

    return Item(
        id=hashlib.sha256(item_url.encode()).hexdigest()[:12],
        source_name=f"Reddit r/{subreddit}",
        source_url=f"https://www.reddit.com/r/{subreddit}/",
        item_url=item_url,
        item_title=title,
        item_author=author,
        published_at=published,
        source_type="reddit",
        content_type="discussion",
        summary=title,
        key_claims=key_claims,
        raw_content=raw,
        status="raw",
        queue_type="breaking",
        engagement={
            "score": score,
            "comments": num_comments,
            "velocity": velocity,
            "permalink": permalink,
        },
        reddit_score=score,
        reddit_comments=num_comments,
        reddit_permalink=permalink,
    )


def fetch_subreddit(subreddit: str, sort: str = "top", time_filter: str = "week", max_results: int = 10) -> list[dict]:
    payload = {
        "subreddit": subreddit,
        "sort": sort,
        "time_filter": time_filter,
        "max_results": max_results,
    }
    resp = _execute("REDDIT_RETRIEVE_REDDIT_POST", payload)
    if not resp.get("ok"):
        logger.warning("[reddit] error fetching r/%s: %s", subreddit, resp.get("error"))
        return []
    data = resp.get("data", {})
    if isinstance(data, dict) and "children" in data:
        return data["children"]
    if isinstance(data, dict) and "data" in data:
        return data["data"].get("children", [])
    return []


def collect_reddit(dry_run: bool = False, limit_per_sub: int | None = None) -> int:
    """Collect top posts from configured subreddits, dropping stale/low-signal items."""
    if not _composio_bin():
        logger.info("[reddit] composio CLI not available; skipping Reddit collection")
        return 0

    total = 0
    for subs in REDDIT_COMMUNITIES.values():
        for sub, default_limit in subs.items():
            max_results = limit_per_sub or default_limit
            logger.info("[Reddit r/%s] sort=top time=week limit=%s", sub, max_results)
            posts = fetch_subreddit(sub, sort="top", time_filter="week", max_results=max_results)
            new = 0
            for post in posts:
                item = _post_to_item(post, sub)
                if item_exists(item.item_url):
                    logger.info("  dedupe: %s", item.item_title[:60])
                    continue
                ok, reason = passes_recency_gate(item)
                if not ok:
                    logger.info("  skipped (recency): %s — %s", item.item_title[:60], reason)
                    continue
                if not dry_run:
                    save_item(item)
                logger.info("  saved: %s", item.item_title[:60])
                new += 1
            logger.info("  %s new", new)
            total += new
    logger.info("Reddit collection complete: %s new items", total)
    return total


if __name__ == "__main__":
    collect_reddit()
