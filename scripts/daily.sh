#!/usr/bin/env bash
# Daily runner for the LinkedIn pipeline.
# Intended for cron or systemd timer.
# Runs collect → score → draft-today → content analysis → dashboard regeneration.
set -euo pipefail

ROOT="/opt/linkedin-pipeline"
VENV="$ROOT/.venv/bin/python"
LOG="$ROOT/data/logs/daily-$(date +%Y-%m-%d).log"

mkdir -p "$ROOT/data/logs"
{
  echo "=== Daily run started at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  cd "$ROOT"

  # 1. Collect new signals
  echo "--- collect ---"
  "$VENV" run.py collect --limit 5 || echo "collect completed with errors"

  # 2. Score
  echo "--- score ---"
  "$VENV" run.py score --limit 100 || echo "score completed with errors"

  # 3. Draft today's post (queued, not published)
  echo "--- draft-today ---"
  "$VENV" run.py draft-today --limit 1 || echo "draft-today completed with no strong signal"

  # 4. Analyze queued drafts for relevance/perfection
  echo "--- analyze-content ---"
  "$VENV" run.py analyze-content --limit 10 --no-llm || echo "analyze-content completed with errors"

  # 5. Regenerate review dashboard
  echo "--- review-dashboard ---"
  "$VENV" run.py review-dashboard || echo "review-dashboard completed with errors"

  echo "=== Daily run finished at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
} >& "$LOG"
