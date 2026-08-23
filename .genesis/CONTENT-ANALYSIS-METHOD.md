# Daily Content Relevance + Perfection Analysis

## Goal
Run a daily automated check on queued/planned content to confirm it is still relevant, accurate, and matches the day's editorial slot. This is a **bounded** analysis: it does not rewrite without human approval, but it flags issues and proposes adjustments.

## What is analyzed
1. **Relevance** — Does the signal still match today's pillar? Are there newer/better sources?
2. **Accuracy** — Are claims, links, and cited sources still valid? (link check + recency)
3. **Perfection** — Voice, hook, length, hashtags, image fit, CTA strength against the 7-day calendar.

## Outputs
- Markdown report: `.genesis/analysis/YYYY-MM-DD--analysis.md`
- Score card per queued item: `relevance_score`, `accuracy_score`, `perfection_score` (0–100)
- Proposed actions: `keep`, `update_source`, `rewrite_draft`, `skip`, `replace_image`
- Human approval required before any rewrite or publish.

## Suggested implementation
A new module `pipeline/content_analyst.py` with:
- `analyze_queued_items(for_date=None)` — loads queued/ready drafts and scores them.
- `link_health_check(url)` — HEAD request with timeout.
- `recency_check(item)` — compare `published_at` to today; older than 48h degrades relevance.
- `perfection_score(draft, day_plan)` — heuristic + optional LLM call.
- CLI command: `python run.py analyze-content --date YYYY-MM-DD --notify`.

## Failure tolerance
- A failing link must not crash the run; it lowers `accuracy_score`.
- If LLM is unavailable, fall back to rule-based heuristics.
- No automatic publish; flagged items require operator decision.
