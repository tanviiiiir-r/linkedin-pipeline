# CURRENT — linkedin-pipeline

**Last updated:** 2026-08-24 23:54 UTC+3
**Active milestone:** M3 — VPS deploy + Hermes integration + live dry-run publish
**Status:** M2.6 ✅ DONE; dashboard v3 ✅ DONE; M3 🔄 IN PROGRESS (deployment artifacts ready, live deploy pending VPS access).

## M2.6 verification result

- **L4 verdict:** APPROVE (`.genesis/checkpoints/M2.6-VERIFY.md`).
- **Review findings:** 0 Critical, 0 Warning (2 resolved), 3 Info.
- **Tests:** 60 passed.
- **Lint:** ruff clean.

## What is live

- `RECENCY_POLICY` constants with `planned_selection_floor`.
- `Item` fields `queue_type`, `expires_at`, `engagement`.
- `pipeline/freshness.py` recency/engagement gates.
- `pipeline/calendar.py` hybrid selection: breaking → planned evergreen fallback → no_strong_signal.
- `pipeline/scoring.py` founder_signal pillar + engagement boost.
- `plan-content` CLI for seeding planned evergreen items.
- `pipeline/review_dashboard.py` v3: light-studio LinkedIn-style preview, progress bars, toasts.
- Branch `codex/hybrid-calendar-v3` pushed.

## M3 remaining

1. Deploy updated repo to Hostinger VPS.
2. Start MCP server + review dashboard server via systemd.
3. Configure Traefik routes with basic auth.
4. End-to-end dry run: collect → score → draft-today --with-image → review → approve → publish --dry-run.
5. Verify Hermes container can reach MCP server and review server.

## Blockers

- VPS SSH access / deployment credentials not available to this session.
