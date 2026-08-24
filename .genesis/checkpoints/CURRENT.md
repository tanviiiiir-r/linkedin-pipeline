# CURRENT — linkedin-pipeline

**Last updated:** 2026-08-24 16:49
**Active milestone:** M2.6 — Hybrid calendar + freshness-first selection
**Status:** M2.5 ✅ DONE; M2.6 🔄 IN PROGRESS.

## M2.5 verification result

- **L4 verdict:** APPROVE (`.genesis/checkpoints/M2.5-VERIFY.md`).
- **Review findings:** 0 Critical, 3 Warning, 4 Info (all non-blocking).
- **Tests:** 42 passed (37 existing + 5 new review-dashboard tests).

## M2.6 build progress

- Recency policy constants added to `config/settings.py`.
- `Item` model extended with `queue_type`, `expires_at`, `engagement`.
- `pipeline/freshness.py` recency/engagement helpers and gates implemented.
- All collectors updated to produce timestamps and engagement metadata.
- `pipeline/calendar.py` hybrid selection (breaking → planned → no-strong-signal) implemented.
- `pipeline/scoring.py` updated for `founder_signal` pillar detection and generic engagement bonus.
- `pipeline/hermes.py` and `mcp_server.py` updated to handle tuple return and no-strong-signal path.
- Tests: 57 passed, ruff clean.

## What remains

1. L4 code review of M2.6 changes.
2. Merge/push `codex/hybrid-calendar-v3`.
3. Continue M3 (VPS deploy + Hermes integration) after user confirms.

## Blockers

- None.
