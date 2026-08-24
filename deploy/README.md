# Deployment artifacts

These files are copied to `/opt/linkedin-pipeline` on the VPS and wired into systemd + Traefik.

## Files

- `review-dashboard.service` — systemd unit for the review dashboard server (`python run.py review-server`).
- `mcp-server.service` — systemd unit for the MCP server (`python mcp_server.py`).
- `review-dashboard-traefik-dynamic.yml` — Traefik dynamic config for the review dashboard route + basic auth.
- `mcp-server-traefik-dynamic.yml` — Traefik dynamic config for the MCP server route + basic auth.
- `install.sh` (optional) — helper to install services and start them.

## Network model

- MCP server listens on `127.0.0.1:8000` inside the host network namespace.
- Review server listens on `0.0.0.0:8080` inside the host network namespace.
- Traefik runs in Docker and reaches the host via the Docker bridge IP `172.18.0.1`.
- Hermes container reaches the MCP server via the same bridge IP and HTTP basic auth (Traefik forwards to the backend).

## Traefik basic auth

Generate a password hash on a machine with `htpasswd`:

```bash
htpasswd -nb hermes YOUR_PASSWORD | sed 's/\$/$$/g'
```

Replace `CHANGEME` in both `*-traefik-dynamic.yml` files with the produced string.

## Installation

On the VPS as root:

```bash
cp deploy/review-dashboard.service /etc/systemd/system/
cp deploy/mcp-server.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now review-dashboard mcp-server
# Copy Traefik dynamic configs into the Traefik config directory used by your Docker compose.
cp deploy/*-traefik-dynamic.yml /opt/traefik/conf.d/
docker compose -f /opt/traefik/docker-compose.yml restart
```

## Environment

Both services read from `/opt/linkedin-pipeline/.env`. Required variables include:

- `MCP_AUTH_TOKEN` — bearer token for MCP tool auth.
- `RUNPOD_API_KEY`, `RUNPOD_POD_ID`, `COMFY_PROXY_URL` — for image generation.
- LinkedIn OAuth credentials (`LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`, `LINKEDIN_REDIRECT_URI`).
- Optional LLM provider overrides (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`).
