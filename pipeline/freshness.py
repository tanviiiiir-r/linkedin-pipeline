"""Recency and engagement helpers for the hybrid calendar.

Every collector must produce items with a clear published_at or collected_at.
This module centralizes the recency gating policy so the scoring/selection
logic can stay simple and testable.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from config.settings import RECENCY_POLICY, STALE_EVERGREEN_TERMS
from pipeline.storage import Item

logger = logging.getLogger(__name__)


_NOW = datetime.now(timezone.utc)


def _parse_dt(value: str | None) -> datetime | None:
    """Best-effort parse of ISO/HTTP timestamps."""
    if not value:
        return None
    value = value.strip()
    # Common ISO variants
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z"):
        try:
            return datetime.strptime(value, fmt)  # noqa: DTZ007
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        pass
    for fmt in ("%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            dt = datetime.strptime(value, fmt)  # noqa: DTZ007
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def item_age_hours(item: Item, *, use: str = "published") -> float | None:
    """Return hours since the item's published or collected timestamp."""
    ts = item.published_at if use == "published" else item.collected_at
    if not ts:
        ts = item.collected_at if use == "published" else item.published_at
    dt = _parse_dt(ts)
    if not dt:
        return None
    return max(0.0, (_NOW - dt).total_seconds() / 3600.0)


def age_penalty_score(hours: float | None, *, start: float | None = None) -> int:
    """Exponential age penalty after the grace period."""
    if hours is None:
        return -30
    start = start or RECENCY_POLICY["age_penalty_start_hours"]
    if hours <= start:
        return 0
    # Penalty grows by ~3 points per day beyond the grace period
    days = (hours - start) / 24.0
    return int(-min(50, days * 3))


def _is_stale_evergreen(item: Item, hours: float | None) -> bool:
    """Return True if the item is an old recycled evergreen topic."""
    if hours is None:
        return True
    text = f"{item.item_title} {item.summary} {item.raw_content}".lower()
    if not any(term in text for term in STALE_EVERGREEN_TERMS):
        return False
    # Allow genuinely fresh mentions if they reference a specific recent release/repo.
    return not (hours <= 48 and any(signal in text for signal in ["released", "launched", "new repo", "github.com", "show hn"]))


def engagement_score(item: Item) -> int:
    """Return a small bonus/penalty based on source-specific engagement."""
    e = item.engagement or {}
    score = 0
    source = item.source_type
    floors = RECENCY_POLICY["engagement_floors"].get(source, {})

    if source == "reddit":
        pts = e.get("score", 0)
        cmts = e.get("comments", 0)
        min_score = floors.get("score", 30)
        min_comments = floors.get("comments", 10)
        if pts >= min_score and cmts >= min_comments:
            score += min(25, pts // 20)
        elif pts < min_score or cmts < min_comments:
            score -= 15

    elif source == "github-search":
        spd = e.get("stars_per_day", 0.0)
        min_spd = floors.get("stars_per_day", 5.0)
        if spd >= min_spd:
            score += min(25, int(spd * 2))
        else:
            score -= 15

    elif source == "github-trending":
        if e.get("is_trending"):
            score += 20
        else:
            score -= 10

    # Generic engagement fallback for text-based news sources (RSS/Hacker News).
    # Capped lower than source-specific rules and only applied when the source is not governed
    # by explicit engagement floors (e.g., reddit, github).
    if source in {"rss", "hackernews", "news"}:
        generic_score = e.get("score", 0)
        generic_comments = e.get("comments", 0)
        if generic_score or generic_comments:
            boost = min(15, (generic_score // 25) + (generic_comments // 12))
            # Only apply if it represents meaningful discussion
            if generic_comments >= 5 or generic_score >= 50:
                score += boost

    return score


def passes_recency_gate(item: Item, *, source_type: str | None = None) -> tuple[bool, str]:
    """Check whether an item is fresh enough and engaged enough to keep.

    Returns (ok, reason). Collectors should drop items where ok is False.
    """
    st = source_type or item.source_type
    max_age = RECENCY_POLICY["source_max_age_hours"].get(st, 72)
    hours = item_age_hours(item, use="published")
    if hours is None:
        hours = item_age_hours(item, use="collected")
    if hours is None:
        return False, "no timestamp"
    if hours > max_age:
        return False, f"older than {max_age}h ({hours:.1f}h)"

    # Engagement floors
    floors = RECENCY_POLICY["engagement_floors"].get(st, {})
    e = item.engagement or {}
    if st == "reddit":
        if e.get("score", 0) < floors.get("score", 30):
            return False, f"reddit score {e.get('score', 0)} < {floors.get('score', 30)}"
        if e.get("comments", 0) < floors.get("comments", 10):
            return False, f"reddit comments {e.get('comments', 0)} < {floors.get('comments', 10)}"
    if st == "github-search" and e.get("stars_per_day", 0.0) < floors.get("stars_per_day", 5.0):
        return False, f"stars/day {e.get('stars_per_day', 0.0):.1f} < {floors.get('stars_per_day', 5.0):.1f}"

    # Stale evergreen filter
    if _is_stale_evergreen(item, hours):
        return False, "stale evergreen topic"

    return True, ""


def planned_decay_score(item: Item) -> int:
    """Penalty for planned evergreen items as they age past their half-life."""
    if not item.expires_at:
        return 0
    expires = _parse_dt(item.expires_at)
    if not expires:
        return 0
    now = _NOW
    if now >= expires:
        return -50
    half_life = timedelta(hours=RECENCY_POLICY["planned_half_life_hours"])
    age = now - (_parse_dt(item.published_at) or now)
    if age <= timedelta(0):
        return 0
    # Halve the bonus every half-life period
    periods = age / half_life
    return int(-min(40, periods * 8))


def is_fresh_breaking(item: Item) -> bool:
    """Convenience check for breaking queue items."""
    ok, _ = passes_recency_gate(item)
    return ok


def format_age(item: Item) -> str:
    hours = item_age_hours(item, use="published")
    if hours is None:
        hours = item_age_hours(item, use="collected")
    if hours is None:
        return "unknown age"
    if hours < 1:
        return f"{int(hours * 60)}m"
    if hours < 48:
        return f"{int(hours)}h"
    return f"{int(hours / 24)}d"


if __name__ == "__main__":
    # Quick sanity check
    item = Item(
        source_name="Reddit r/test",
        source_url="https://reddit.com/r/test",
        item_url="https://reddit.com/r/test/comments/x",
        item_title="MCP is the future",
        source_type="reddit",
        content_type="discussion",
        summary="Generic MCP discussion",
        published_at=(datetime.now(timezone.utc) - timedelta(hours=12)).isoformat(),
        engagement={"score": 120, "comments": 35},
    )
    print("age_hours:", item_age_hours(item))
    print("penalty:", age_penalty_score(item_age_hours(item)))
    print("engagement:", engagement_score(item))
    print("gate:", passes_recency_gate(item))
    print("stale evergreen?", _is_stale_evergreen(item, item_age_hours(item)))
