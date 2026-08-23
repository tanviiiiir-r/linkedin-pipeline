#!/usr/bin/env bash
# Convenience wrapper to run the pipeline daily from cron or terminal.
cd /opt/data/content-pipeline || exit 1
export $(grep -v '^#' /opt/data/.env | xargs -d '\n')
exec .venv/bin/python run.py daily "$@"
