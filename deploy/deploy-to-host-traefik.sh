#!/bin/bash
# Deploy linkedin-pipeline review dashboard Traefik config
# Usage: update TRAEFIK_DIR and RELOAD_CMD, then run as root on host.

TRAEFIK_DIR="/etc/traefik"  # <-- change to your Traefik config directory
RELOAD_CMD="systemctl reload traefik || docker restart traefik"  # <-- change to your reload command

SRC="/opt/data/linkedin-pipeline-latest/deploy/review-dashboard-traefik-dynamic.yml"
DEST="$TRAEFIK_DIR/dynamic/linkedin-review.yml"

mkdir -p "$(dirname "$DEST")"
cp "$SRC" "$DEST"
chmod 644 "$DEST"

echo "Deployed $DEST"
eval "$RELOAD_CMD"
