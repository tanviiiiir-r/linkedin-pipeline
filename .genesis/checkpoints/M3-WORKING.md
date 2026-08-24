# M3 WORKING NOTES

**Branch:** codex/review-dashboard
**Goal:** Add a browser-based draft review/preview dashboard for LinkedIn drafts.
**Access model:** Traefik public route with basic auth (phone-friendly).
**Scope:** One tab — LinkedIn. Extensible for Twitter/X, newsletter, analytics later.

## Files to create
- pipeline/review_dashboard.py
- pipeline/review_server.py
- data/review/assets/style.css
- deploy/review-dashboard.service (systemd unit)
- deploy/review-dashboard.yml (docker-compose Traefik labels variant)

## Files to modify
- config/settings.py: REVIEW_DIR
- pipeline/approval.py: skip_draft, edit_draft
- pipeline/hermes.py: review-dashboard and review-server CLI commands
- mcp_server.py: optional tools for dashboard state (if needed)

## Design decisions
- Server binds 0.0.0.0:8080 on host.
- Traefik routes https://review.hermes-agent-xqcr.srv1921473.hstgr.cloud to 172.18.0.1:8080 (host network mode).
- Basic auth via Traefik middleware. Password hash generated with htpasswd.
- Dashboard writes to markdown files directly, with a .bak copy before edit.
- Skipped drafts moved to data/review/skipped/ (not deleted).
- Regenerate image uses image_for_post(force_comfy=True) and refreshes preview.
