"""Select best item(s) for today's editorial day type from scored items.

Supports a hybrid selection strategy:
- breaking queue (fresh signals, recency + engagement gated)
- planned queue (evergreen, day-matched, with half-life decay)
- manual fallback when nothing clears the threshold.
"""
from __future__ import annotations

import logging
from datetime import date

from config.calendar import DayPlan, day_plan
from config.settings import RECENCY_POLICY
from pipeline.freshness import (
    age_penalty_score,
    engagement_score,
    format_age,
    item_age_hours,
    passes_recency_gate,
    planned_decay_score,
)
from pipeline.scoring import ScoreResult, score_item
from pipeline.storage import Item, load_planned_items

logger = logging.getLogger(__name__)


def _match_score(item: Item, score: ScoreResult, day_plan: DayPlan) -> int:
    """Return a rough relevance score for ranking items against the day plan."""
    points = 0
    lens_terms = set(day_plan.lens.lower().replace(",", " ").split())
    text = " ".join(
        [
            item.item_title or "",
            item.summary or "",
            " ".join(item.key_claims or []),
            item.raw_content or "",
        ]
    ).lower()
    points += sum(2 for term in lens_terms if len(term) > 2 and term in text)

    # Favor source bias
    source_bias = {s.lower() for s in day_plan.source_bias}
    if item.source_name and item.source_name.lower() in source_bias:
        points += 10

    # Favor pillar alignment
    if score.pillar == day_plan.post_type:
        points += 15
    elif score.pillar and score.pillar in day_plan.post_type:
        points += 5

    # Confidence/signal weighted moderately
    points += score.pillar_confidence // 10
    points += score.signal_strength // 10

    # Prefer items that have not already been drafted
    if item.status in ("drafted", "approved", "published"):
        points -= 50

    # Freshness penalties + engagement bonuses
    hours = item_age_hours(item, use="published")
    points += age_penalty_score(hours)
    points += engagement_score(item)

    return points


def _select_from_pool(
    items: list[Item],
    day_plan: DayPlan,
    limit: int,
    *,
    require_fresh: bool = False,
) -> list[tuple[Item, ScoreResult, int]]:
    """Rank a candidate pool and optionally drop anything not fresh."""
    results: list[tuple[Item, ScoreResult, int]] = []
    for item in items:
        score = score_item(item)
        rank = _match_score(item, score, day_plan)
        if require_fresh:
            ok, reason = passes_recency_gate(item)
            if not ok:
                logger.debug("%s not fresh enough: %s", item.item_title[:60], reason)
                continue
        results.append((item, score, rank))
    results.sort(key=lambda x: x[2], reverse=True)
    return results


def select_for_day(
    items: list[Item],
    day_plan: DayPlan,
    limit: int = 1,
    *,
    mode: str = "hybrid",
    threshold: int | None = None,
) -> tuple[list[tuple[Item, ScoreResult]], str]:
    """Return the best item/score pairs for the given day plan.

    Args:
        items: Candidate items, ideally already scored.
        day_plan: The editorial plan for the target day.
        limit: Max pairs to return.
        mode: "breaking" | "planned" | "hybrid".
        threshold: Minimum rank to accept a breaking result. Defaults to policy.

    Returns:
        A tuple of (selected pairs, selection_note).
        The note explains whether the result came from breaking/planned/manual.
    """
    threshold = threshold if threshold is not None else RECENCY_POLICY["selection_threshold"]

    if mode in ("breaking", "hybrid"):
        breaking = _select_from_pool(items, day_plan, limit, require_fresh=True)
        if breaking and breaking[0][2] >= threshold:
            note = "breaking signal"
            if mode == "hybrid":
                note = f"breaking signal (age {format_age(breaking[0][0])})"
            logger.info(
                "Calendar selection for %s: %d breaking candidates, top rank %d",
                day_plan.day_name,
                len(breaking),
                breaking[0][2],
            )
            return [(item, score) for item, score, _ in breaking[:limit]], note

    if mode in ("planned", "hybrid"):
        planned = _select_from_pool(
            load_planned_items(limit=100),
            day_plan,
            limit,
            require_fresh=False,
        )
        # Apply planned half-life decay after ranking
        planned = [
            (item, score, rank + planned_decay_score(item))
            for item, score, rank in planned
        ]
        planned.sort(key=lambda x: x[2], reverse=True)
        # Planned items need less strict threshold than breaking signals, with a floor
        planned_threshold = max(RECENCY_POLICY["planned_selection_floor"], threshold - 20)
        if planned and planned[0][2] >= planned_threshold:
            logger.info(
                "Calendar selection for %s: %d planned candidates, top rank %d",
                day_plan.day_name,
                len(planned),
                planned[0][2],
            )
            return [(item, score) for item, score, _ in planned[:limit]], "planned evergreen"

    # No strong signal
    logger.info("Calendar selection for %s: no strong signal (threshold %d)", day_plan.day_name, threshold)
    return [], "no_strong_signal"


def select_for_today(
    items: list[Item],
    limit: int = 1,
    for_date: date | None = None,
    *,
    mode: str = "hybrid",
    threshold: int | None = None,
) -> tuple[list[tuple[Item, ScoreResult]], str]:
    """Convenience wrapper that resolves today's day plan and selects items."""
    plan = day_plan(for_date)
    return select_for_day(items, plan, limit=limit, mode=mode, threshold=threshold)


def items_for_today_post_type(
    items: list[Item],
    limit: int = 1,
    for_date: date | None = None,
) -> list[Item]:
    """Return just the items best matching today's post type."""
    selected, _ = select_for_today(items, limit=limit, for_date=for_date)
    return [item for item, _ in selected]
