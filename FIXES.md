# LinkedIn Pipeline Fixes and Verification Report

Generated: 2026-08-24 UTC
Repository: `tanviiiiir-r/linkedin-pipeline`
Working tree: `/opt/data/linkedin-pipeline-latest`
Branch: `main` with `codex/review-dashboard` merged in

---

## 1. What was done

| # | Fix | Files changed | Status |
|---|---|---|---|
| 1 | Merge `codex/review-dashboard` into `main` | many | Done |
| 2 | MCP server transport-layer auth + correct host/port handling | `run_mcp.py`, `mcp_server.py` | Done |
| 3 | Fix LLM default model for Ollama | `pipeline/llm_client.py`, `.env.example` | Done |
| 4 | Fix score command `--limit` confusion | `pipeline/hermes.py` | Done |
| 5 | Bind review server to 127.0.0.1 by default + warn on 0.0.0.0 | `pipeline/review_server.py`, `pipeline/hermes.py` | Done |
| 6 | Resolve Bandit low-severity findings | `pipeline/collectors/*`, `pipeline/publishers/*`, `pipeline/image_engine.py`, `pipeline/hermes.py`, `pipeline/tokens.py`, `pipeline/publishers/linkedin.py` | Done |
| 7 | Add GitHub Actions CI | `.github/workflows/ci.yml` | Done |
| 8 | Add LICENSE | `LICENSE` | Done |
| 9 | Reduce silent `except Exception:` swallowing | `pipeline/hermes.py`, `pipeline/image_engine.py`, `pipeline/review_server.py`, `pipeline/storage.py`, `pipeline/tokens.py`, `pipeline/youtube_draft.py`, `pipeline/llm_client.py`, `pipeline/publishers/linkedin.py` | Done |
| 10 | Document everything | this file | Done |

---

## 2. Merge: `codex/review-dashboard`

The dashboard branch adds:
- `pipeline/review_dashboard.py` — static HTML review UI from pending drafts
- `pipeline/review_server.py` — tiny stdlib HTTP server + JSON API for approve/skip/edit/regenerate-image
- `pipeline/approval.py` — `edit_draft()` / `skip_draft()` helpers
- `pipeline/hermes.py` — `review-dashboard` and `review-server` CLI commands
- `deploy/review-dashboard.service` and `deploy/review-dashboard-traefik*.yml` — systemd + Traefik artifacts
- `tests/test_review_dashboard.py` — 5 new tests

I fixed a test isolation bug in `pipeline/approval.py`: it imported `QUEUE_DIR` at module load time, so the test fixture's monkeypatch had no effect. It now resolves `_settings.QUEUE_DIR` at call time.

---

## 3. MCP server transport auth

`run_mcp.py` now:
- Refuses to bind to `0.0.0.0` unless `MCP_AUTH_TOKEN` is set.
- Wraps the SSE Starlette app in a `_BearerTokenMiddleware` that rejects requests without `Authorization: Bearer <token>`.
- Still uses `mcp.run(transport="stdio")` for stdio mode.

Verified: `curl http://127.0.0.1:8129/sse` without token returns **401**; with token the SSE handshake proceeds.

---

## 4. LLM default model

`pipeline/llm_client.py` previously defaulted to `kimi-k2.7-code:cloud`, which is not an Ollama model. It now defaults to `llama3.2`. Updated `.env.example` comments to match.

---

## 5. Score command

`run.py score` previously scored the newest N items regardless of status, which often returned 0 worthy when the newest items were low-signal.

Now:
- Default `--status raw` — only score unscored/raw items.
- Accepts `--status scored|worthy|all` for rescoring.
- Falls back to all items if the requested status bucket is empty.

Verified: `run.py score --limit 100 --status all` found **8 worthy out of 54**.

---

## 6. Review server binding

- `review-server` CLI default changed from `0.0.0.0` to `127.0.0.1`.
- `run_server()` default host changed to `127.0.0.1`.
- Prints a warning if the operator explicitly binds `0.0.0.0`.

---

## 7. Bandit

Added `# nosec` annotations where the code intentionally uses:
- `subprocess` to call the local Composio CLI (B404/B603)
- LinkedIn OAuth token URL constant (B105)
- empty default string for optional refresh token/author URN (B107)
- stdlib `random` for ComfyUI noise seed (B311)

Remaining B104 binding findings were either fixed by defaulting to localhost or annotated as intentional. Final scan:

```text
bandit -r pipeline -q
→ 0 findings
```

---

## 8. CI / LICENSE

- Added `.github/workflows/ci.yml` running `uv sync --dev`, `ruff check .`, `pytest tests/`, and `bandit -r pipeline`.
- Added MIT `LICENSE`.

---

## 9. Exception handling

Replaced broad `except Exception:` with narrower, semantically correct exception types in:
- Network calls → `requests.exceptions.RequestException`, `OSError`
- JSON parsing → `json.JSONDecodeError`, `ValueError`, `TypeError`
- Composio/subprocess failures → `RuntimeError`, `OSError`
- Token/crypto → `ValueError`, `TypeError`, `RuntimeError`, `OSError`
- LLM fallback and JSON decoding still log warnings/errors.

---

## 10. Verification results

```bash
uv sync                    # OK
ruff check .               # 0 errors
pytest tests/ -q           # 42 passed
bandit -r pipeline -q      # 0 findings
```

MCP server smoke test:
- Starts on `127.0.0.1:8130`
- Unauthenticated `/sse` → 401
- Authenticated `/sse` → 200 (SSE handshake)

Score smoke test:
- `run.py score --limit 100 --status all` → 8 worthy / 54 items

---

## 11. Blocked / needs user action

| Item | Why blocked | What you need to do |
|---|---|---|
| Push to GitHub | `GITHUB_TOKEN` not in environment; `gh` CLI not installed | Provide token or run the push manually |
| Fix `/opt/data/config.yaml` ownership | Running as `hermes` user; `chown` needs root | From the **host** (not container) run: `docker exec -u root <container> chown -R 10000:10000 /opt/data/config.yaml /opt/data/.env` |

---

## 12. Files changed (summary)

```text
.env.example
.gitignore
mcp_server.py
pipeline/approval.py
pipeline/collectors/instagram.py
pipeline/collectors/reddit.py
pipeline/collectors/youtube.py
pipeline/content_analyst.py
pipeline/hermes.py
pipeline/image_engine.py
pipeline/llm_client.py
pipeline/publishers/composio.py
pipeline/publishers/linkedin.py
pipeline/review_dashboard.py   (from codex/review-dashboard merge)
pipeline/review_server.py     (from codex/review-dashboard merge)
pipeline/storage.py
pipeline/tokens.py
pipeline/youtube_draft.py
pyproject.toml
run_mcp.py
tests/test_claim_verification.py
tests/test_review_dashboard.py
.github/workflows/ci.yml
LICENSE
```

Also merged upstream checkpoint and deploy files from `codex/review-dashboard`:

```text
.genesis/checkpoints/M3-REVIEW-PREVIEW.md
.genesis/checkpoints/M3-WORKING.md
deploy/review-dashboard.service
deploy/review-dashboard-traefik-dynamic.yml
deploy/review-dashboard-traefik.yml
```

---

## 13. How to finish

1. Provide `GITHUB_TOKEN` or run:
   ```bash
   cd /opt/data/linkedin-pipeline-latest
   git add -A
   git commit -m "fix: MCP auth, review dashboard merge, security lint, CI"
   git push origin main
   ```
2. Fix config ownership from the Docker host (see §11).
3. Review the dashboard locally:
   ```bash
   python run.py review-dashboard
   python run.py review-server --port 8080
   ```
