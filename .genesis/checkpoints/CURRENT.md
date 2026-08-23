# CURRENT — linkedin-pipeline

**Last updated:** 2026-08-23
**Active milestone:** M2.5 — 7-day content calendar + LLM humanizer + Founder Signal
**Status:** ✅ DONE — L1 build complete; awaiting L4 verification.

## What was done

- Rebased to `origin/main` (`8183f83`) which already merged M2 auth/logging fixes.
- Created `pipeline/voice.py` with persona, tone, no-go words, signature phrases, per-day word budgets, and CTAs.
- Created `pipeline/drafting_v2.py` LLM humanizer with JSON parsing, schema validation via Pydantic `Draft`, rule-based fallback, and Founder Signal question enforcement.
- Created `pipeline/calendar.py` to select best item(s) for the current day type from scored/worthy items.
- Updated `pipeline/hermes.py` with `draft-today` CLI subcommand (supports `--dry-run`, `--date`).
- Updated `mcp_server.py` with `draft_today` MCP tool and fixed tool registration order.
- Added `tests/test_calendar.py` and `tests/test_drafting_v2.py`; fixed `tests/test_storage.py` isolation bug.
- Full test suite green: 29 passed. Demo commands verified.

## Verification artifacts

- `.genesis/checkpoints/M2.5-REVIEW.md` — severity-classified review with 0 Critical, 3 Warning, 4 Info findings.
- Tests: `python -m pytest tests/` → 29 passed.
- Demo: `python run.py draft-today --dry-run` → Sunday synthesis post.
- Demo: `python run.py draft-today --dry-run --date 2026-08-29` → Founder Signal post ending with discussion question.

## What is next

1. Run L4 VERIFY for M2.5 using a separate model/context.
2. On APPROVE, append live row to `.genesis/implementation-notes.html` and update `PLAN.md` / `DONE.html` progress.
3. Begin M3 — VPS deploy + Hermes integration + live dry-run publish.

## Blockers

- None.

## Notes

- 3 pre-existing ruff warnings remain (not introduced by M2.5): `pipeline/dedupe.py` set comprehension, `pipeline/dedupe.py` SIM103, `pipeline/verify.py` FLY002.
- Remaining M2.5 actions captured as warnings in M2.5-REVIEW.md: raw-item fallback gate, LLM fallback metric, optional LLM rerank for Saturday.
