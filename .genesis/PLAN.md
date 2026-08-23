# PLAN — linkedin-pipeline

The machine-parseable implementation plan. Mirrors the milestone table in `DONE.html`.
Sliced so each milestone ships in one L1 BUILD pass, verified by L4 VERIFY.

## Milestones

### M1 — Baseline code review of existing codebase
- **Outcome:** A written, severity-classified deep code review of the entire current codebase, accepted by an independent L4 verifier.
- **Phase (GSD):** review
- **Files / freeze boundary:** Source files are read-only for M1. Allowed to write: `.genesis/checkpoints/M1-REVIEW.md`, `.genesis/checkpoints/CURRENT.md`, `.genesis/implementation-notes.html`, `.genesis/PLAN.md`.
- **Demo command:** `cat .genesis/checkpoints/M1-REVIEW.md | grep -c "^### "`
- **Success criteria:** Review has ≥1 Critical, ≥1 Warning, and ≥1 Info finding; all findings have file paths and actionable remediation; L4 verifier returns APPROVE.
- **Loops:** L1, L4
- **Skills:** GSD canon + tdd + modular-architecture + production-readiness + security-engineering
- **Token budget:** 25000
- **Status:** ✅ DONE — 2026-08-23

### M2 — MCP server auth + VPS deployment artifacts
- **Outcome:** MCP server has bearer-token auth, deployment configs (systemd/Traefik/Docker), and is ready for install on the VPS.
- **Phase (GSD):** build
- **Files / freeze boundary:** `mcp_server.py`, `run_mcp.py`, `.env.example`, new files under `deploy/` and `.genesis/checkpoints/M2-*`.
- **Demo command:** `curl -H "Authorization: Bearer $MCP_AUTH_TOKEN" http://$VIP:8000/sse`
- **Success criteria:** MCP server rejects unauthenticated requests; systemd service starts; Traefik route exposes `/sse` with basic auth or network ACL.
- **Loops:** L1, L3, L4
- **Skills:** GSD canon + tdd + security-engineering + devops
- **Token budget:** 25000
- **Status:** pending

### M2.5 — 7-day content calendar + LLM humanizer + Founder Signal
- **Outcome:** The pipeline drafts day-appropriate, voice-aware LinkedIn posts for each day of the week, including a Saturday Founder Signal designed to attract founders.
- **Phase (GSD):** build
- **Files / freeze boundary:** `config/calendar.py`, `pipeline/calendar.py`, `pipeline/voice.py`, `pipeline/drafting_v2.py`, updates to `pipeline/hermes.py`, `mcp_server.py`, tests, and `.genesis/checkpoints/M2.5-*`.
- **Demo command:** `python run.py draft-today --dry-run`
- **Success criteria:** `draft-today` selects an item matching the current day type, generates a human-sounding LinkedIn post via LLM, validates output against Pydantic, and saves it to the queue; tests pass.
- **Loops:** L1, L3, L4
- **Skills:** GSD canon + tdd + modular-architecture + production-readiness
- **Token budget:** 25000
- **Status:** 🔄 IN PROGRESS

### M3 — VPS deploy + Hermes integration + live dry-run publish
- **Outcome:** Repo deployed on Hostinger VPS, Hermes container can reach MCP server, full collect→score→draft→approve→publish dry-run works end-to-end.
- **Phase (GSD):** ship
- **Files / freeze boundary:** VPS state, Hermes config, `.env` on server, `.genesis/checkpoints/M3-*`, source files as needed.
- **Demo command:** `docker exec hermes-agent-xqcr-hermes-agent-1 curl -s http://172.18.0.1:8000/sse`
- **Success criteria:** Hermes lists MCP tools; collect/score/draft produce items; approve + dry-run publish returns success.
- **Loops:** L1, L2, L4
- **Skills:** GSD canon + tdd + security-engineering + devops + vercel-deploy
- **Token budget:** 25000
- **Status:** pending

---

## Progress (loops append here on milestone completion — newest last)

- M1 done — 2026-08-23: baseline review approved by L4 verifier; 3 Critical, 7 Warning, 5 Info findings recorded.
