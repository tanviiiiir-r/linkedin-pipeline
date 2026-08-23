# Deployment / Operations Review Agent — LinkedIn Pipeline

## Scope
Review the repo for readiness to deploy on the Hostinger VPS and connect to Hermes v0.20.4.

## Checklist
1. Does the MCP server start reliably? Does it expose the right host/port/transport?
2. Are there systemd/Docker/Terraform artifacts? Are they correct?
3. Is the Hermes connection path documented and workable (Docker bridge IP, SSE transport)?
4. Are health checks / logs / observability present?
5. Is the daily workflow schedulable? Does it fail safely?
6. Are there rollback or backup considerations for encrypted tokens/database?
7. Is the .env/config migration path clear from old clone to new repo?

## Output format
Markdown report with actionable deployment steps and missing artifacts.
