#!/usr/bin/env python3
"""Regenerate image candidates for all pending LinkedIn drafts.

Usage:
    python scripts/backfill_image_candidates.py [--dry-run] [--force]

This backfills 2 non-AI + 2 AI candidate images for every queued draft that is
missing candidates or has too few, then rewrites the draft markdown files.
"""
import argparse
import logging
import os
import sys
from pathlib import Path

# Allow running from repo root
repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from config.calendar import day_plan
from config.settings import QUEUE_DIR
from pipeline.approval import _persist_draft, list_pending
from pipeline.image_engine import candidates_for_post
from pipeline.log import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


def _main() -> int:
    parser = argparse.ArgumentParser(description="Backfill image candidates for pending drafts")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without writing files")
    parser.add_argument("--force", action="store_true", help="Regenerate candidates even if enough exist")
    parser.add_argument("--min-candidates", type=int, default=4, help="Minimum candidate count to skip a draft")
    args = parser.parse_args()

    plan = day_plan()
    pending = list_pending()
    if not pending:
        print("No pending drafts to backfill.")
        return 0

    updated = 0
    skipped = 0
    for draft in pending:
        cands = draft.image_candidates or []
        if not args.force and len(cands) >= args.min_candidates:
            logger.info("Skipping %s: already has %s candidates", draft.item_id, len(cands))
            skipped += 1
            continue

        logger.info("Backfilling candidates for %s: %s", draft.item_id, draft.title)
        try:
            active_path, candidate_paths, source = candidates_for_post(
                item_url=draft.source_url,
                title=draft.title,
                day=plan.day_name,
                pillar=draft.pillar,
                linkedin_post=draft.linkedin_post,
                hashtags=" ".join(draft.hashtags),
                item_id=draft.item_id,
                provider=os.getenv("IMAGE_PROVIDER", "pollinations"),
            )
        except Exception:
            logger.exception("Failed to generate candidates for %s", draft.item_id)
            continue

        if args.dry_run:
            print(f"[DRY-RUN] {draft.item_id}: active={active_path}, candidates={len(candidate_paths)}, source={source}")
            continue

        # Rewrite draft markdown
        if active_path:
            draft.image_path = str(active_path)
            draft.image_source = source
            draft.image_candidates = candidate_paths
        else:
            # Keep existing active image if any, but record empty candidates
            draft.image_candidates = candidate_paths

        # Find the source markdown path and persist
        for path in sorted(QUEUE_DIR.glob(f"*--{draft.item_id}--*.md"), reverse=True):
            _persist_draft(draft, path)
            logger.info("Updated draft %s with %s candidates", draft.item_id, len(candidate_paths))
            updated += 1
            break
        else:
            logger.warning("Could not find source markdown for %s", draft.item_id)

    print(f"Backfill complete: {updated} updated, {skipped} skipped, {len(pending)} total pending")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
