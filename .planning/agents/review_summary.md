# Combined Review Summary — LinkedIn Pipeline Working Tree

Generated after rebasing onto origin/main (133191e). Tools used: pytest, ruff, bandit, semgrep, pip-audit, manual inspection.

## Executive Verdict
The repo is a **working prototype** with a clear architecture. The current working-tree changes add needed LLM and YouTube capabilities, but they introduce **regressions in mcp_server.py** and several **security/maintenance gaps** that should be fixed before VPS deployment.

## What is already good
- All 19 tests pass (including the new youtube_draft tests and the fixed token tests).
- Token encryption uses Fernet with a PBKDF2-derived key and constant salt (acceptable for local-at-rest encryption).
- Human-in-the-loop approval gate is wired through both CLI and MCP tools.
- LLM client is provider-agnostic and gracefully degrades when Ollama is unreachable.
- youtube_draft has sane URL validation and fallback behavior.
- No known vulnerable dependencies (`pip-audit` clean).

## Critical / must-fix before deploy

### 1. `youtube_to_draft` is registered after `if __name__ == "__main__":`
- File: `mcp_server.py` line 286 vs 282
- Impact: The function is decorated, but because it appears after the `__main__` guard, `mcp.run()` will **not** expose it to clients in normal import/start paths. Hermes will not see the tool.
- Fix: move the function definition (and all other `@mcp.tool()` definitions) above the `__main__` block.

### 2. `mcp_server.py` has unused imports and ruff violations
- `cmd_queue` imported but unused.
- `save_item` and `find_duplicate` imported inside `collect_source` but unused.
- Import block unsorted in `collect_source`.
- Impact: lint noise, dead code, potential import-side effects.
- Fix: remove unused imports; run `ruff check --fix .` and `ruff format`.

### 3. Broad `except Exception: pass` blocks hide failures
- 30 instances across `pipeline/`, `config/`, `mcp_server.py`.
- Notable: `pipeline/tokens.py:88`, `pipeline/youtube_draft.py:69/96`, `pipeline/collectors/instagram.py:76`, `pipeline/hermes.py` many places.
- Impact: silent failures make debugging impossible; may hide token corruption, collector outages, or YouTube page changes.
- Fix: log at minimum (`logging.warning` / `logging.exception`) and re-raise where the caller should know.

### 4. MD5 used for URL hashing
- Files: `pipeline/storage.py`, `pipeline/dedupe.py` (and any other place using `hashlib.md5`).
- Bandit flags B324 (High) even though this is not a security use-case.
- Impact: static analysis noise; in some FIPS environments MD5 is disabled.
- Fix: use `hashlib.sha256(...).hexdigest()[:12]` or add `usedforsecurity=False`.

### 5. No MCP server authentication
- `run_mcp.py` defaults to `127.0.0.1` but docs say bind to `0.0.0.0` on VPS.
- No bearer token, basic auth, or network ACL.
- Impact: anyone who can reach port 8000 can collect, score, draft, approve, and publish.
- Fix: add `MCP_AUTH_TOKEN` in `.env`, FastAPI middleware to require `Authorization: Bearer <token>`, and reject requests without it.

### 6. Subprocess calls use partial path (`composio`)
- Files: `pipeline/collectors/instagram.py`, `pipeline/collectors/reddit.py`, `pipeline/collectors/youtube.py`, `pipeline/publishers/composio.py`.
- Bandit B607/B603 (Low/High) because `composio` is invoked via PATH and user-controlled payload is JSON-encoded.
- Impact: PATH hijacking or unexpected Composio CLI behavior.
- Fix: resolve absolute path with `shutil.which` once, validate it, and pass explicit absolute binary path.

### 7. SQL string formatting for index creation
- File: `pipeline/storage.py:90` — `f"CREATE INDEX IF NOT EXISTS idx_items_{idx} ON items({idx})"`.
- Semgrep flags it as formatted SQL; `idx` is a hardcoded tuple of strings, but the pattern is risky.
- Fix: build the statement with a whitelist of column names, or use f-string only after validating against a known set.

### 8. HTTP (not HTTPS) adapter mounted in requests session
- File: `pipeline/hermes.py:65`.
- Semgrep flags unencrypted HTTP request. The adapter is used for local HTTP in some edge cases, but the default should be HTTPS-only.
- Fix: only mount the HTTPS adapter unless `ALLOW_HTTP` is set, and document why HTTP is needed.

### 9. LinkedIn token exchange stores URN even when fetch fails
- `pipeline/hermes.py` / `mcp_server.py` both save `author_urn or ""` when exchanging code.
- Impact: empty URN persists; publish later fails with "author URN" error unless re-fetched.
- Fix: fail fast if URN cannot be fetched and `openid` scope is included; warn operator clearly.

### 10. `.env.example` does not document new LLM variables
- New code uses `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TIMEOUT`.
- Impact: operators will not know how to configure Ollama/OpenAI/Anthropic.
- Fix: add commented-out LLM section to `.env.example` and update docs.

## Medium issues
- No health-check endpoint for the MCP server (useful for Traefik/uptime monitoring).
- No rate limiting on public tools; `collect_items`/`score_items` could be hammered.
- `generate_linkedin_auth_url` reloads `config.settings` but the rest of `mcp_server.py` already imported the old values, so the redirect-URI override is fragile.
- `Draft` model is imported twice in `pipeline/youtube_draft.py` (top and bottom), indicating a circular-import workaround that should be refactored.
- No license file (already noted in REPO_ANALYSIS.md).

## Low / style issues
- Heavy use of `print()` in `pipeline/hermes.py` (82 calls); should migrate to `logging` with levels for prod.
- `pyproject.toml` has `pytest-cov` and `ruff` in dev deps but ruff was not installed in this environment.
- No CI/GitHub Actions for tests or lint.
- `youtube_transcript_api` is used optionally but not in `requirements.txt`; add to optional deps.

## Recommended priority order
1. Move `youtube_to_draft` above `__main__` and fix ruff errors.
2. Add MCP bearer-token auth middleware + `.env.example` update.
3. Replace broad `except: pass` with logging + specific exceptions.
4. Swap MD5 for SHA256 for URL hashing.
5. Resolve `composio` binary path absolutely.
6. Fix SQL formatting and HTTP adapter semgrep findings.
7. Add `.env.example` LLM docs and optional dependency.
8. Add health-check endpoint and rate-limiting.

After these, the code is ready for VPS deployment and Hermes registration.
