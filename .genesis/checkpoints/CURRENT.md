# CURRENT — linkedin-pipeline

**Last updated:** 2026-08-24 16:51
**Active milestone:** M3 — VPS deploy + Hermes integration + live dry-run publish
**Status:** M2.6 ✅ DONE; M3 🔄 IN PROGRESS.

## M2.6 verification result

- **L4 verdict:** APPROVE (`.genesis/checkpoints/M2.6-VERIFY.md`).
- **Review findings:** 0 Critical, 0 Warning (2 resolved), 3 Info.
- **Tests:** 57 passed.
- **Lint:** ruff clean.

## M2.6 what is live

- `RECENCY_POLICY` constants in `config/settings.py` with `planned_selection_floor`.
- `Item` fields `queue_type`, `expires_at`, `engagement`.
- `pipeline/freshness.py` recency/engagement gates + source-aware generic bonus.
- All collectors produce timestamps and engagement metadata.
- `pipeline/calendar.py` hybrid selection: breaking → planned (with floor) → no_strong_signal.
- `pipeline/scoring.py` founder_signal pillar + generic engagement boost.
- `pipeline/hermes.py` and `mcp_server.py` handle tuple return/no-signal path.
- Branch `codex/hybrid-calendar-v3` committed and ready to push.

## What remains (M3)

1. Push `codex/hybrid-calendar-v3` and merge to `main`.
2. Deploy updated repo to Hostinger VPS.
3. Start MCP server + review dashboard server via systemd.
4. Configure Traefik routes with basic auth.
5. End-to-end dry run: collect → score → draft-today --with-image → review → approve → publish --dry-run.
6. Verify Hermes container can reach MCP server and review server.

## Blockers

- None.
