# M1 — Baseline Deep Code Review

**Project:** linkedin-pipeline  
**Scope:** Full working tree (source files read only; no edits made during M1).  
**Review date:** 2026-08-23  
**Skills invoked:** gsd-code-review, modular-architecture, production-readiness, security-engineering.  
**Tools used:** pytest, ruff, bandit, semgrep, pip-audit, graphify, manual cross-file inspection.

## Executive summary

The repo is a **functional prototype** for a Hermes-driven LinkedIn content pipeline. The architecture is modular and the human-in-the-loop approval gate is correctly wired. However, before production deployment it has **critical gaps in MCP server security**, **widespread silent exception swallowing**, **several static-analysis findings**, and **a tooling regression that hides `youtube_to_draft` from MCP clients**. These must be addressed in M2/M3.

---

## Findings by severity

### Critical (3)

#### C1 — `youtube_to_draft` is registered after `if __name__ == "__main__":`
- **File:** `mcp_server.py` line 286 (after `__main__` guard at line 282)
- **Why it matters:** `mcp.run()` enumerates tools at import time. Decorators after `__main__` are executed when the module is imported as a script, but not when imported by `run_mcp.py` or an ASGI worker. Hermes will not see the tool.
- **Remediation:** Move all `@mcp.tool()` definitions above the `if __name__ == "__main__":` block.
- **Verification:** `python -c "from mcp_server import mcp; print([t for t in mcp.list_tools()])"` must include `youtube_to_draft`.

#### C2 — MCP server has no authentication
- **Files:** `mcp_server.py`, `run_mcp.py`
- **Why it matters:** Docs instruct binding to `0.0.0.0` on the VPS. Without a bearer token, basic auth, or network ACL, any actor reaching port 8000 can collect, score, draft, approve, and publish LinkedIn content.
- **Remediation:** Add `MCP_AUTH_TOKEN` env var; add FastAPI middleware requiring `Authorization: Bearer <token>` for all non-health endpoints; reject with 401 otherwise.
- **Verification:** `curl http://$VIP:8000/sse` returns 401; `curl -H "Authorization: Bearer $MCP_AUTH_TOKEN" http://$VIP:8000/sse` returns 200.

#### C3 — Broad `except Exception: pass` hides failures across the codebase
- **Files:** 30 occurrences in `pipeline/`, `config/`, `mcp_server.py`, `tests/conftest.py`
- **Examples:**
  - `pipeline/tokens.py:88` — silently ignores chmod failure (token DB may remain world-readable).
  - `pipeline/hermes.py:87,97,227,265,344,349,354,359,609` — collection/scoring errors swallowed; empty runs look successful.
  - `pipeline/youtube_draft.py:69,96` — caption extraction failures silently ignored.
  - `pipeline/llm_client.py:127,166` — Ollama model-list and completion errors swallowed.
- **Why it matters:** Failures become invisible; operators cannot debug collector outages, token corruption, or LLM misconfiguration.
- **Remediation:** Replace silent `pass` with `logging.exception(...)` or re-raise where the caller must know. Introduce a small `log.py` using stdlib `logging`.
- **Verification:** Run `pytest tests/` and `python run.py --dry-run collect --limit 1`; no silent failures; logs show warnings for recoverable issues.

### Warning (6)

#### W1 — MD5 used for URL/item hashing
- **Files:** `pipeline/storage.py`, `pipeline/dedupe.py` (and anywhere `hashlib.md5` is called)
- **Why it matters:** Bandit flags B324 (High). Even though MD5 here is not a security primitive, it causes CI/static-analysis noise and may be disabled in FIPS environments.
- **Remediation:** Use `hashlib.sha256(url.encode()).hexdigest()[:12]` or add `usedforsecurity=False`.
- **Verification:** `bandit -r pipeline` no longer reports B324 for hashing.

#### W2 — `composio` subprocess invoked via partial PATH
- **Files:** `pipeline/collectors/instagram.py:27`, `pipeline/collectors/reddit.py:38`, `pipeline/collectors/youtube.py:24`, `pipeline/publishers/composio.py:46`
- **Why it matters:** Bandit B607/B603. A hijacked PATH or unexpected Composio binary could lead to command execution or data leakage. User-controlled JSON payloads are passed as `-d` arguments.
- **Remediation:** Resolve the absolute path once with `shutil.which("composio")`, validate it, and pass the absolute binary. Treat Composio JSON payloads as untrusted input and validate shapes before serialization.
- **Verification:** `bandit -r pipeline/collectors pipeline/publishers` no longer reports B607/B603.

#### W3 — SQL string formatting for index creation
- **File:** `pipeline/storage.py:90`
- **Code:** `conn.execute(f"CREATE INDEX IF NOT EXISTS idx_items_{idx} ON items({idx})")`
- **Why it matters:** Semgrep flags formatted SQL. Although `idx` is a hardcoded tuple, the pattern is risky and triggers security scanners.
- **Remediation:** Build statements from a whitelist of column names or use `textwrap.dedent` + explicit string formatting after validation.
- **Verification:** `semgrep --config=auto pipeline/storage.py` no longer flags the query.

#### W4 — HTTP adapter mounted on requests session
- **File:** `pipeline/hermes.py:65`
- **Code:** `_session.mount("http://", _adapter)`
- **Why it matters:** Semgrep flags unencrypted HTTP transport. HTTP may be needed for local Ollama, but the default global session should be HTTPS-only.
- **Remediation:** Only mount HTTP adapter when `ALLOW_HTTP=true` or for explicitly local URLs; document the exception for Ollama.
- **Verification:** `semgrep --config=auto pipeline/hermes.py` no longer flags the session.

#### W5 — LinkedIn token exchange persists empty author URN
- **Files:** `pipeline/hermes.py:cmd_linkedin_exchange`, `mcp_server.py:exchange_linkedin_code`
- **Why it matters:** `save_tokens(..., author_urn or "", ...)` stores an empty string when the userinfo fetch fails. Later publish fails with "Could not determine LinkedIn author URN" instead of failing fast during auth.
- **Remediation:** If the `openid` scope is included and userinfo returns no `sub`, fail the exchange with a clear message and do not store tokens.
- **Verification:** `python run.py linkedin-exchange --code fake` with mocked failed userinfo exits non-zero and does not write tokens.

#### W6 — `mcp_server.py` has unused/dead imports and ruff violations
- **File:** `mcp_server.py`
- **Issues:** `cmd_queue` imported but unused; `save_item` and `find_duplicate` imported inside `collect_source` but unused; import block unsorted.
- **Why it matters:** Dead code increases maintenance burden and import-side-effect risk.
- **Remediation:** Remove unused imports; run `ruff check --fix .` and `ruff format`.
- **Verification:** `python -m ruff check .` exits clean.

#### W7 — LLM-generated drafts are not schema-validated
- **Files:** `pipeline/llm_client.py`, `pipeline/youtube_draft.py`
- **Why it matters:** `context-graph.json` invariant inv-4 requires all structured LLM outputs to be validated. Currently `draft_from_summary()` strips Markdown code fences and calls `json.loads()`, but the resulting dict is passed straight to `_build_draft_from_llm()` without validating against a Pydantic model. A malformed model response could produce empty fields or wrong types.
- **Remediation:** Parse the LLM JSON dict through a small Pydantic schema (or `Draft.model_validate` with sensible defaults) before building the `Draft`; fall back to rule-based `draft_item()` on validation failure.
- **Verification:** Add a test asserting that malformed LLM JSON still returns a valid `Draft` via fallback, and a test asserting well-formed LLM JSON produces expected fields.

### Info (5)

#### I1 — `.env.example` does not document new LLM variables
- **File:** `.env.example`
- **Why it matters:** `pipeline/llm_client.py` reads `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TIMEOUT`. Operators cannot configure Ollama/OpenAI/Anthropic without reading source.
- **Remediation:** Add a commented LLM section to `.env.example` and update `docs/HERMES_SETUP.md`.

#### I2 — No license file
- **Why it matters:** REPO_ANALYSIS.md already notes this. Public repo without license creates legal ambiguity for reuse.
- **Remediation:** Add `LICENSE` (MIT recommended for tooling).

#### I3 — No CI/GitHub Actions
- **Why it matters:** Tests pass locally but there is no automated guard against regressions.
- **Remediation:** Add `.github/workflows/ci.yml` running `pytest` and `ruff check .` on PRs.

#### I4 — Heavy `print()` usage in `pipeline/hermes.py`
- **Why it matters:** 82 print statements make production logging noisy and hard to filter.
- **Remediation:** Migrate to `logging` with levels; keep CLI output via a simple formatter if desired.

#### I5 — `youtube_transcript_api` is optional but not in requirements
- **File:** `pipeline/youtube_draft.py`, `requirements.txt`
- **Why it matters:** The code gracefully falls back, but the optional richer transcript path is not discoverable.
- **Remediation:** Add `youtube-transcript-api` to `[project.optional-dependencies]` in `pyproject.toml` or document it.

---

## Architecture / maintainability observations

- **Good:** `Item` and `Draft` Pydantic models are central, well-typed bridges between modules (high betweenness in graphify report).
- **Good:** Storage abstraction cleanly falls back from Supabase to SQLite + markdown.
- **Concern:** `pipeline/hermes.py` is a kitchen-sink orchestrator (~700 LOC) doing collection, scoring, drafting, newsletter, auth, and CLI wiring. Consider splitting into `pipeline/commands/`.
- **Concern:** `pipeline/youtube_draft.py` imports `Draft` at the bottom to avoid a circular import with `pipeline.drafting`; this signals a coupling issue worth refactoring.

---

## Security / threat-model notes

- **Credential storage:** `.env` is gitignored; tokens are Fernet-encrypted at rest. Good.
- **Transport:** LinkedIn API calls use HTTPS. MCP server currently uses unauthenticated HTTP/SSE on the Docker bridge; fix C2 before exposing to any wider network.
- **Untrusted input:** YouTube URLs and LinkedIn OAuth codes flow into the system. YouTube URL parsing is strict; OAuth code is passed directly to LinkedIn's token endpoint (safe), but URN fetch failure is not handled well (W5).
- **Prompt injection:** Not applicable in the rule-based pipeline today. The new LLM drafting in `pipeline/youtube_draft.py` and `pipeline/llm_client.py` introduces an LLM surface; output is JSON-parsed but not schema-validated. Add Pydantic validation for LLM-generated drafts.

---

## Recommended action priority

1. **C2 + I1:** Add MCP bearer-token auth and document LLM env vars before any VPS exposure.
2. **C1 + W6:** Fix MCP tool registration and ruff-clean the file.
3. **C3:** Introduce `logging` and eliminate silent `except Exception: pass` blocks.
4. **W1, W2, W3, W4, W5:** Resolve static-analysis findings (MD5, composio PATH, SQL format, HTTP adapter, URN handling).
5. **I2, I3, I4, I5:** Add license, CI, structured logging, and optional dependency docs.

---

## Verification checklist

- [ ] L4 verifier APPROVEs this review as accurate and actionable.
- [ ] M2 succeeds with `curl -H "Authorization: Bearer $MCP_AUTH_TOKEN" http://$VIP:8000/sse`.
- [ ] M3 succeeds with Hermes reaching the MCP server and running a dry-run publish end-to-end.
