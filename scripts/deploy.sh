#!/usr/bin/env bash
# Deploy the content pipeline to run daily on a VPS.
set -euo pipefail

# NOTE: /opt/data/config.yaml must be owned by hermes (uid 10000) for Telegram
# notifications to work. If it is root-owned, run from the host as root:
#   docker exec -u root <container> chown 10000:10000 /opt/data/config.yaml

REPO_DIR="/opt/data/content-pipeline"
SERVICE_NAME="content-pipeline"
USER="hermes"

# Ensure repo exists and is on main
cd "$REPO_DIR"
git pull origin main

# Create systemd user service
mkdir -p ~/.config/systemd/user

cat > ~/.config/systemd/user/${SERVICE_NAME}.service <<EOF
[Unit]
Description=Secure AI Engineering content pipeline daily run

[Service]
Type=oneshot
WorkingDirectory=%h/content-pipeline
ExecStart=%h/content-pipeline/.venv/bin/python run.py daily --collect-limit 10 --draft-limit 1 --newsletter-limit 1 --min-confidence 50 --min-signal 50 --with-image
EnvironmentFile=%h/.env
EOF

cat > ~/.config/systemd/user/${SERVICE_NAME}.timer <<EOF
[Unit]
Description=Run content pipeline daily at 08:00 UTC

[Timer]
OnCalendar=*-*-* 08:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable ${SERVICE_NAME}.timer
systemctl --user start ${SERVICE_NAME}.timer

echo "Deployment complete. Timer status:"
systemctl --user status ${SERVICE_NAME}.timer --no-pager
