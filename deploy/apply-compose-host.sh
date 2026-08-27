#!/bin/bash
set -e
COMPOSE_DIR=/docker/hermes-agent-xqcr

# Backup existing compose
cp "$COMPOSE_DIR/docker-compose.yml" "$COMPOSE_DIR/docker-compose.yml.bak.$(date +%s)"

# Deploy updated compose
cp "$COMPOSE_DIR/data/linkedin-pipeline-latest/deploy/docker-compose-updated.yml" "$COMPOSE_DIR/docker-compose.yml"

# Add review password to .env if not present
if ! grep -q "^REVIEW_PASSWORD=" "$COMPOSE_DIR/.env"; then
    echo "REVIEW_PASSWORD=LinkedInReview2026!" >> "$COMPOSE_DIR/.env"
fi

cd "$COMPOSE_DIR"
docker compose up -d

echo "Done. Dashboard should be live at https://review.caraxis.online"
