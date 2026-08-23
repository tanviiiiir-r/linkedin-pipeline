"""Select best item(s) for today's editorial day type from scored/worthy items."""
import logging
from datetime import date

from config.calendar import DayPlan, day_plan
from pipeline.scoring import ScoreResult
from pipeline.storage import Item

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

    return points


def select_for_day(
    items: list[Item],
    day_plan: DayPlan,
    limit: int = 1,
) -> list[tuple[Item, ScoreResult]]:
    """Return the best item/score pairs for the given day plan.

    Args:
        items: Candidate items, ideally already scored.
        day_plan: The editorial plan for the target day.
        limit: Max pairs to return.

    Returns:
        A list of (item, score) tuples ranked for the day plan.
    """
    from pipeline.scoring import score_item

    scored: list[tuple[Item, ScoreResult, int]] = []
    for item in items:
        score = score_item(item)
        rank = _match_score(item, score, day_plan)
        scored.append((item, score, rank))

    scored.sort(key=lambda x: x[2], reverse=True)
    logger.info(
        "Calendar selection for %s: %d candidates, top rank %d",
        day_plan.day_name,
        len(scored),
        scored[0][2] if scored else 0,
    )
    return [(item, score) for item, score, _ in scored[:limit]]


def select_for_today(
    items: list[Item],
    limit: int = 1,
    for_date: date | None = None,
) -> list[tuple[Item, ScoreResult]]:
    """Convenience wrapper that resolves today's day plan and selects items."""
    plan = day_plan(for_date)
    return select_for_day(items, plan, limit=limit)


def items_for_today_post_type(
    items: list[Item],
    limit: int = 1,
    for_date: date | None = None,
) -> list[Item]:
    """Return just the items best matching today's post type."""
    return [item for item, _ in select_for_today(items, limit=limit, for_date=for_date)]
