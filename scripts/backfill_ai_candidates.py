"""Regenerate AI image candidates for pending drafts using the latest prompt engineering.

This backfill keeps non-AI candidates (article/OG/stock) and replaces only the
AI-generated candidates (ai_environment, ai_message, ai_focus, ai_pov, ai_stock)
with freshly generated images from the improved pipeline.
"""
import logging
import sys
from pathlib import Path

# Ensure project root is on PYTHONPATH when run directly
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import DATA_DIR, QUEUE_DIR, ensure_dirs
from pipeline.approval import list_pending
from pipeline.drafting import Draft, save_draft
from pipeline.image_engine import candidates_for_post
from pipeline.log import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

IMAGE_CANDIDATES_DIR = DATA_DIR / "image_candidates"


def _delete_ai_files(candidates_dir: Path) -> None:
    """Remove previously generated AI images so they are regenerated."""
    if not candidates_dir.exists():
        return
    for p in candidates_dir.iterdir():
        if p.is_file() and any(token in p.name for token in ("ai_environment", "ai_message", "ai_focus", "ai_pov", "ai_stock")):
            logger.info("Removing old AI candidate: %s", p)
            p.unlink(missing_ok=True)


def backfill_pending() -> None:
    ensure_dirs()
    pending = list_pending()
    logger.info("Backfilling AI candidates for %s pending drafts", len(pending))
    for draft in pending:
        item_id = draft.item_id
        candidates_dir = IMAGE_CANDIDATES_DIR / item_id
        _delete_ai_files(candidates_dir)

        active, candidates, source = candidates_for_post(
            item_url=draft.source_url,
            title=draft.title,
            day="",
            pillar=draft.pillar,
            linkedin_post=draft.linkedin_post,
            hashtags=" ".join(draft.hashtags),
            item_id=item_id,
        )

        if not candidates:
            logger.warning("No candidates generated for %s", item_id)
            continue

        draft.image_path = str(active) if active else ""
        draft.image_source = source
        draft.image_candidates = [str(c) for c in candidates]
        save_draft(draft, QUEUE_DIR / "pending")
        logger.info("Updated %s: active=%s source=%s candidates=%s", item_id, draft.image_path, source, len(candidates))


if __name__ == "__main__":
    backfill_pending()
