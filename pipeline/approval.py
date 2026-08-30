"""Human-in-the-loop approval queue."""
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import settings as _settings
from pipeline.drafting import Draft, _draft_markdown, _parse_draft_markdown, load_drafts

logger = logging.getLogger(__name__)


def _queue_dir() -> Path:
    """Resolve the current queue directory from settings so tests can monkeypatch it."""
    return _settings.QUEUE_DIR


def _skipped_dir() -> Path:
    return _queue_dir() / "skipped"


def _approved_dir() -> Path:
    return _queue_dir() / "approved"


def list_pending() -> list[Draft]:
    """Return drafts awaiting human approval."""
    return [d for d in load_drafts(_queue_dir()) if not d.approved and not d.published]


def list_ready_to_publish() -> list[Draft]:
    """Return drafts approved but not yet published."""
    return [d for d in load_drafts(_queue_dir()) if d.approved and not d.published]


def list_approved() -> list[Draft]:
    """Return all approved drafts (including published), newest first."""
    _approved_dir().mkdir(parents=True, exist_ok=True)
    drafts: list[Draft] = []
    for path in sorted(_approved_dir().glob("*.md"), reverse=True):
        draft = _parse_draft_markdown(path.read_text())
        if draft:
            drafts.append(draft)
    return drafts


def list_rejected() -> list[Draft]:
    """Return rejected/skipped drafts, cleaned up weekly."""
    cleanup_rejected()
    _skipped_dir().mkdir(parents=True, exist_ok=True)
    drafts: list[Draft] = []
    for path in sorted(_skipped_dir().glob("*.md"), reverse=True):
        draft = _parse_draft_markdown(path.read_text())
        if draft:
            drafts.append(draft)
    return drafts


def cleanup_rejected(max_age_days: int = 7) -> int:
    """Delete rejected drafts older than max_age_days. Returns count deleted."""
    skipped = _skipped_dir()
    if not skipped.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    deleted = 0
    for path in skipped.glob("*.md"):
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if mtime < cutoff:
            try:
                path.unlink()
                deleted += 1
            except OSError:
                logger.exception("Failed to delete old rejected draft %s", path)
    return deleted


def _find_draft_path(item_id: str) -> Path | None:
    for path in sorted(_queue_dir().glob("*.md"), reverse=True):
        text = path.read_text()
        draft = _parse_draft_markdown(text)
        if draft and draft.item_id == item_id:
            return path
    return None


def _find_in_folder(item_id: str, folder: Path) -> Path | None:
    if not folder.exists():
        return None
    for path in sorted(folder.glob("*.md"), reverse=True):
        text = path.read_text()
        draft = _parse_draft_markdown(text)
        if draft and draft.item_id == item_id:
            return path
    return None


def _persist_draft(draft: Draft, path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(_draft_markdown(draft))
    tmp.replace(path)


def approve_draft(item_id: str) -> bool:
    """Mark a queued draft as approved and move it to the approved folder."""
    path = _find_draft_path(item_id)
    if not path:
        # Already approved?
        return bool(_find_in_folder(item_id, _approved_dir()))
    text = path.read_text()
    draft = _parse_draft_markdown(text)
    if not draft:
        return False
    draft.approved = True
    draft.published = False
    draft.approved_at = datetime.now(timezone.utc).isoformat()

    _approved_dir().mkdir(parents=True, exist_ok=True)
    approved_path = _approved_dir() / path.name
    _persist_draft(draft, approved_path)
    try:
        path.unlink()
    except OSError:
        logger.exception("Failed to remove queued draft after approval %s", path)
    return True


def mark_published(item_id: str) -> bool:
    """Mark an approved draft as published."""
    path = _find_in_folder(item_id, _approved_dir())
    if not path:
        # Fallback to queue dir
        path = _find_draft_path(item_id)
    if not path:
        return False
    text = path.read_text()
    draft = _parse_draft_markdown(text)
    if not draft:
        return False
    draft.published = True
    _persist_draft(draft, path)
    return True


def edit_draft(item_id: str, linkedin_post: str) -> bool:
    """Update the LinkedIn post body of a queued draft, keeping a .bak copy."""
    path = _find_draft_path(item_id)
    if not path:
        return False
    text = path.read_text()
    draft = _parse_draft_markdown(text)
    if not draft:
        return False
    draft.linkedin_post = linkedin_post.strip()
    backup = path.with_suffix(".md.bak")
    backup.write_text(text)
    _persist_draft(draft, path)
    return True


def skip_draft(item_id: str, skipped_dir: Path | None = None, feedback: str = "") -> bool:
    """Move a queued draft to a skipped folder (default: QUEUE_DIR/skipped).

    Returns True if a draft was moved. Idempotent: if already skipped, returns True.
    """
    path = _find_draft_path(item_id)
    if not path:
        # Already rejected?
        return bool(_find_in_folder(item_id, _skipped_dir()))
    text = path.read_text()
    draft = _parse_draft_markdown(text)
    if not draft:
        return False
    if feedback:
        draft.newsletter_section += f"\n\n**Rejection feedback:** {feedback}"
    draft.approved = False
    draft.published = False

    skipped = skipped_dir or _skipped_dir()
    skipped.mkdir(parents=True, exist_ok=True)
    dest = skipped / path.name
    _persist_draft(draft, dest)
    try:
        path.unlink()
    except OSError:
        logger.exception("Failed to remove queued draft after skip %s", path)
    return True
