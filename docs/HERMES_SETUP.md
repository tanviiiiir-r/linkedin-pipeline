# Hermes Setup Guide

This document explains how to connect the LinkedIn Pipeline MCP server to Hermes running on a VPS.

## What this gives Hermes

Once connected, Hermes can call these tools:

| Tool | Purpose | Safe? |
|---|---|---|
| `pipeline_status` | Show data dir, auth, and token status | Yes |
| `collect_items` | Collect RSS/GitHub items | Yes (dry-run by default) |
| `list_collected_items` | Browse collected items | Yes |
| `score_items` | Score items against content pillars | Yes |
| `list_worthy_items` | Show items marked worthy | Yes |
| `draft_posts` | Draft LinkedIn posts from worthy items | Yes (creates queue entries) |
| `list_queue` | Show pending and ready drafts | Yes |
| `approve_draft_by_id` | Approve a draft for publishing | No (human gate) |
| `publish_approved_drafts` | Publish approved drafts to LinkedIn | No (posts content) |
| `youtube_to_draft` | YouTube URL → LLM draft → approval queue | Yes (creates queue entry) |
| `generate_linkedin_auth_url` | Generate LinkedIn OAuth URL | Yes |
| `exchange_linkedin_code` | Save LinkedIn tokens | No (stores auth) |
| `get_linkedin_auth_status` | Check stored token status | Yes |

## Prerequisites

- Hermes Agent running in Docker on the VPS.
- This repo deployed on the host VPS (not inside the Hermes container).
- Python 3.10+ and a virtualenv.
- LinkedIn OAuth app with free products enabled:
  - Share on LinkedIn
  - Sign In with LinkedIn using OpenID Connect
- Ollama running locally or an OpenAI/Anthropic API key for LLM drafting.

## 1. Deploy the pipeline on the VPS

### Clone and install

```bash
ssh root@186.241.23.161
mkdir -p /opt/linkedin-pipeline
cd /opt/linkedin-pipeline
git clone https://github.com/tanviiiiir-r/linkedin-pipeline.git .
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Configure environment

```bash
cp .env.example .env
nano .env
```

Set at minimum:

```env
LINKEDIN_CLIENT_ID=your_client_id
LINKEDIN_CLIENT_SECRET=your_client_secret
LINKEDIN_REDIRECT_URI=https://hermes-agent-xqcr.srv1921473.hstgr.cloud/callback
TOKEN_SECRET=a_strong_random_secret_at_least_32_chars
DATA_DIR=/opt/linkedin-pipeline/data
REQUIRE_APPROVAL=true

# For local Ollama drafting (default on this VPS)
LLM_PROVIDER=ollama
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=kimi-k2.7-code:cloud

# Optional: override with OpenAI/Anthropic
# LLM_PROVIDER=openai
# LLM_API_KEY=sk-...
# LLM_MODEL=gpt-4o-mini
```

Generate a token secret:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## 2. Run the MCP server

### Option A: systemd service (recommended)

Create the service file:

```bash
cat > /etc/systemd/system/linkedin-pipeline-mcp.service <<'SERVICE'
[Unit]
Description=LinkedIn Pipeline MCP Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/linkedin-pipeline
Environment=PATH=/opt/linkedin-pipeline/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin
ExecStart=/opt/linkedin-pipeline/.venv/bin/python /opt/linkedin-pipeline/run_mcp.py --host 0.0.0.0 --port 8000
Restart=unless-stopped

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable --now linkedin-pipeline-mcp
systemctl status linkedin-pipeline-mcp
```

### Option B: run manually

```bash
cd /opt/linkedin-pipeline
source .venv/bin/activate
python run_mcp.py --host 0.0.0.0 --port 8000
```

## 3. Connect Hermes to the MCP server

Hermes runs in a Docker container. The container is on network `hermes-agent-xqcr_default` and can reach the host at `172.18.0.1`.

### Find the host IP from inside the container

```bash
docker exec hermes-agent-xqcr-hermes-agent-1 ip route | grep default
```

Usually the host is `172.18.0.1`.

### Register the MCP server with Hermes

Hermes MCP registration depends on the version. Common methods:

#### Method 1: Hermes config file

Edit Hermes config to add a toolset or MCP server pointing to:

```
http://172.18.0.1:8000/sse
```

#### Method 2: Environment variable or runtime config

If Hermes supports `MCP_SERVERS` env var, add to `/docker/hermes-agent-xqcr/.env`:

```env
MCP_SERVERS='{"linkedin-pipeline":{"url":"http://172.18.0.1:8000/sse","transport":"sse"}}'
```

Then restart the Hermes container:

```bash
cd /docker/hermes-agent-xqcr
docker compose restart
```

#### Method 3: Hermes CLI (if available inside the container)

```bash
docker exec -it hermes-agent-xqcr-hermes-agent-1 /opt/hermes/.venv/bin/hermes mcp add linkedin-pipeline http://172.18.0.1:8000/sse
```

> Replace the URL and command with whatever Hermes v0.20.4 actually supports.

## 4. Authenticate LinkedIn

From the VPS:

```bash
cd /opt/linkedin-pipeline
source .venv/bin/activate
python run.py linkedin-auth-url --redirect-uri https://hermes-agent-xqcr.srv1921473.hstgr.cloud/callback
```

Open the URL, authorize, then:

```bash
python run.py linkedin-exchange --code PASTE_CODE_HERE
python run.py linkedin-status
```

## 5. Test the full flow

### Via CLI

```bash
python run.py --dry-run collect --limit 3
python run.py score --limit 50
python run.py draft --limit 1
python run.py queue
python run.py approve ITEM_ID
python run.py publish --limit 1
```

### Via Hermes

In a Hermes chat, ask:

> “Collect AI news, score them, draft the top one, and show me the queue.”

Hermes should call the MCP tools. Approve the draft, then:

> “Publish the approved draft.”

## 6. Scheduling (optional)

Add a cron job to collect and score automatically:

```bash
crontab -e
```

```cron
0 8 * * * cd /opt/linkedin-pipeline && .venv/bin/python run.py collect --limit 10 && .venv/bin/python run.py score --limit 100
```

Drafting and publishing stay manual or agent-driven to keep the human-in-the-loop.

## 7. YouTube to draft

Hermes can also use:

> “Generate a LinkedIn draft from https://youtube.com/watch?v=…”

This calls `youtube_to_draft`, which extracts the transcript and uses the configured LLM to draft a post. The draft goes into the approval queue like any other.

## Security notes

- The MCP server currently has no built-in auth. Bind it to `127.0.0.1` and put it behind Traefik with basic auth, or restrict Docker network access.
- Keep `.env` and the database out of Git.
- `TOKEN_SECRET` must be strong and backed up; losing it means re-authenticating LinkedIn.
- Never commit `content.db`, `data/`, or `.env`.

## Troubleshooting

| Problem | Fix |
|---|---|
| Hermes cannot reach MCP server | Check firewall, confirm host IP, verify server is listening on `0.0.0.0:8000`. |
| Token tests fail locally | Set `TOKEN_SECRET` before importing `pipeline.tokens`. |
| LinkedIn token exchange fails | Ensure `LINKEDIN_REDIRECT_URI` exactly matches the LinkedIn app setting. |
| Ollama drafting fails | Verify Ollama is running and the model name is correct in `.env`. |
| Traefik blocks SSE | Add a long-timeout route or use stdio transport if Hermes supports it. |

## Files involved

- `/opt/linkedin-pipeline/mcp_server.py` — MCP tool definitions
- `/opt/linkedin-pipeline/run_mcp.py` — server entry point
- `/opt/linkedin-pipeline/pipeline/hermes.py` — CLI orchestrator
- `/opt/linkedin-pipeline/pipeline/publishers/linkedin.py` — LinkedIn auth + publish
- `/opt/linkedin-pipeline/pipeline/tokens.py` — encrypted token store
- `/opt/linkedin-pipeline/pipeline/drafting.py` — draft generation
- `/opt/linkedin-pipeline/config/settings.py` — environment settings
