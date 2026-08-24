# CURRENT — linkedin-pipeline

**Last updated:** 2026-08-24
**Active milestone:** M3 — VPS deploy + Hermes integration + live dry-run publish + review dashboard
**Status:** M2.5 ✅ DONE; M3 🔄 IN PROGRESS.

## M2.5 verification result

- **L4 verdict:** APPROVE (`.genesis/checkpoints/M2.5-VERIFY.md`).
- **Review findings:** 0 Critical, 3 Warning, 4 Info (all non-blocking).
- **Tests:** 42 passed (37 existing + 5 new review-dashboard tests).
- **Demo commands:** passed.

## What was just built

- Browser-based LinkedIn draft review dashboard.
- Single tab (LinkedIn) with stubbed tab extension points.
- Actions: approve, edit (with backup), skip, regenerate image.
- No publish endpoint — human approval gate preserved.
- Tiny Python HTTP server + static HTML generator.
- Traefik route + basic auth deployment artifacts.
- Branch `codex/review-dashboard` pushed to origin.

## What remains

1. L4 code review of the new dashboard code.
2. Deploy to VPS and start review server via systemd.
3. Configure Traefik route with real basic-auth hash.
4. End-to-end dry run: collect → score → draft-today --with-image → review-dashboard → approve → publish --dry-run.
5. Verify Hermes can reach MCP server and review server from container.

## Blockers

- None.
