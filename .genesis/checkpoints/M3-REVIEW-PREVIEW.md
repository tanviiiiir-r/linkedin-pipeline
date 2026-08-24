# M3 Review Dashboard — Pre-L4 Build Notes

## What was built

1. `pipeline/review_dashboard.py`
   - Reads pending drafts from `data/queue/*.md`.
   - Runs `content_analyst.analyze_queued_items()` and attaches scores.
   - Copies draft images into `data/review/images/` for preview.
   - Writes `data/review/index.html` with mobile-friendly dark UI.
   - Single tab: LinkedIn. Tabs stubbed for future workstreams.

2. `pipeline/review_server.py`
   - Tiny HTTP server (stdlib `HTTPServer`) on `0.0.0.0:8080`.
   - Static file serving from `data/review/`.
   - JSON API endpoints:
     - `GET /api/drafts`
     - `POST /api/approve`
     - `POST /api/skip`
     - `POST /api/edit`
     - `POST /api/regenerate-image`
   - No publish endpoint. Human approval gate preserved.

3. `pipeline/hermes.py`
   - `python run.py review-dashboard`
   - `python run.py review-server --host --port`

4. `pipeline/approval.py`
   - Added `edit_draft()` with `.bak` backup.
   - Added `skip_draft()` moving files to `data/queue/skipped/`.

5. `config/settings.py`
   - Added `REVIEW_DIR = DATA_DIR / "review"`.

6. `tests/test_review_dashboard.py`
   - 5 tests: empty dashboard, draft rendering, edit, skip, approve.

7. Deployment artifacts:
   - `deploy/review-dashboard.service` (systemd unit)
   - `deploy/review-dashboard-traefik-dynamic.yml` (dynamic config for Traefik basic-auth route)
   - `deploy/review-dashboard-traefik.yml` (label example for containerized variant)
   - `.env.example` updated.

## Tests
- All 42 tests pass (37 existing + 5 new).

## Security considerations
- Server binds `0.0.0.0:8080`. Public exposure only through Traefik + basic auth.
- API has no authentication of its own; relies on network-level ACL (Traefik middleware).
- No publish endpoint in the dashboard.
- File paths resolved under `REVIEW_DIR` to prevent directory traversal.
- Edit writes create a `.bak` copy before overwrite.

## Known gaps for L4 to scrutinize
1. No CSRF protection on POST endpoints (acceptable because no session cookies; basic auth only).
2. No rate limiting on image regeneration (could wake RunPod repeatedly).
3. Traefik dynamic file currently has placeholder `CHANGEME` hash.
4. Review server uses stdlib HTTPServer; not production-grade, but sufficient for single-operator dashboard.

## Demo commands
- Local: `python run.py review-dashboard && python run.py review-server`
- VPS: systemd service + Traefik route.
