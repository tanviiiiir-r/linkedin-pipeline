# CURRENT — linkedin-pipeline

**Last updated:** 2026-08-23
**Active milestone:** M3 — VPS deploy + Hermes integration + live dry-run publish
**Status:** M2.5 ✅ DONE; M3 🔄 IN PROGRESS.

## M2.5 verification result

- **L4 verdict:** APPROVE (`.genesis/checkpoints/M2.5-VERIFY.md`).
- **Review findings:** 0 Critical, 3 Warning, 4 Info (all non-blocking).
- **Tests:** 29 passed.
- **Demo commands:** passed.
- **Ruff:** 3 pre-existing warnings remain; no regressions.

## What remains

1. Deploy MCP server to VPS host (non-containerized, host network / Docker bridge reachable).
2. Ensure Hermes container can reach host MCP server via Docker bridge.
3. Run live dry-run publish from Hermes against MCP endpoint.
4. Demo command: `docker exec hermes-agent-xqcr-hermes-agent-1 curl -s http://172.18.0.1:8000/sse`.

## Blockers

- None.
