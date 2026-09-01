"""Analytics learning loop for image selection and post performance.

Stores lightweight JSON-lines records so we can later identify which
image sources and visual angles perform best per pillar.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from config.settings import DATA_DIR

logger = logging.getLogger(__name__)

ANALYTICS_DIR = DATA_DIR / "analytics"
ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
SELECTION_LOG = ANALYTICS_DIR / "image_selections.jsonl"


def log_image_selection(
    item_id: str,
    pillar: str,
    title: str,
    source_url: str,
    selected_candidate: str,
    selected_source: str,
    angle: str = "",
    candidate_count: int = 0,
    rank: int = 0,
    post_impressions: int | None = None,
    post_likes: int | None = None,
    post_comments: int | None = None,
    post_saves: int | None = None,
) -> None:
    """Record which image was selected for a post."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "item_id": item_id,
        "pillar": pillar,
        "title": title,
        "source_url": source_url,
        "selected_candidate": selected_candidate,
        "selected_source": selected_source,
        "angle": angle,
        "candidate_count": candidate_count,
        "rank": rank,
        "post_impressions": post_impressions,
        "post_likes": post_likes,
        "post_comments": post_comments,
        "post_saves": post_saves,
    }
    try:
        with open(SELECTION_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.debug("Logged image selection for %s", item_id)
    except OSError:
        logger.exception("Failed to log image selection for %s", item_id)


def summarize_by_pillar() -> dict:
    """Aggregate selection counts and average rank by (pillar, source, angle)."""
    if not SELECTION_LOG.exists():
        return {}
    stats: dict = {}
    try:
        with open(SELECTION_LOG, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                pillar = r.get("pillar", "unknown")
                source = r.get("selected_source", "unknown")
                angle = r.get("angle") or "none"
                key = (pillar, source, angle)
                if key not in stats:
                    stats[key] = {"selections": 0, "ranks": [], "impressions": []}
                stats[key]["selections"] += 1
                stats[key]["ranks"].append(r.get("rank", 0))
                if r.get("post_impressions") is not None:
                    stats[key]["impressions"].append(r["post_impressions"])
    except OSError:
        logger.exception("Failed to read selection log")

    # Build readable summary
    summary: dict = {}
    for (pillar, source, angle), values in stats.items():
        summary.setdefault(pillar, []).append(
            {
                "source": source,
                "angle": angle,
                "selections": values["selections"],
                "avg_rank": round(sum(values["ranks"]) / len(values["ranks"]), 2) if values["ranks"] else 0,
                "avg_impressions": round(sum(values["impressions"]) / len(values["impressions"]), 1) if values["impressions"] else None,
            }
        )
    return summary


def best_sources_per_pillar(top_n: int = 3) -> dict:
    """Return the top N (source, angle) combos per pillar by selection count."""
    summary = summarize_by_pillar()
    result: dict = {}
    for pillar, rows in summary.items():
        rows_sorted = sorted(rows, key=lambda r: r["selections"], reverse=True)[:top_n]
        result[pillar] = rows_sorted
    return result
