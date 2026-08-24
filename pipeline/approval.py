"""Human-in-the-loop approval queue."""
from pathlib import Path

from config.settings import QUEUE_DIR
from pipeline.drafting import Draft, _draft_markdown, _parse_draft_markdown, load_drafts


def list_pending() -> list[Draft]:
    """Return drafts awaiting human approval."""
    return [d for d in load_drafts(QUEUE_DIR) if not d.approved and not d.published]


def list_ready_to_publish() -> list[Draft]:
    """Return drafts approved but not yet published."""
    return [d for d in load_drafts(QUEUE_DIR) if d.approved and not d.published]


def _update_frontmatter(path: Path, item_id: str, key: str, value: bool) -> bool:
    """Atomically update a boolean frontmatter key for the draft matching item_id."""
    text = path.read_text()
    draft = _parse_draft_markdown(text)
    if not draft or draft.item_id != item_id:
        return False
    setattr(draft, key, value)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(_draft_markdown(draft))
    tmp.replace(path)
    return True


def approve_draft(item_id: str) -> bool:
    """Mark a queued draft as approved."""
    for path in sorted(QUEUE_DIR.glob("*.md"), reverse=True):
        if _update_frontmatter(path, item_id, "approved", True):
            return True
    return False


def mark_published(item_id: str) -> bool:
    """Mark a queued draft as published."""
    for path in sorted(QUEUE_DIR.glob("*.md"), reverse=True):
        if _update_frontmatter(path, item_id, "published", True):
            return True
    return False


def _find_draft_path(item_id: str) -> Path | None:
    for path in sorted(QUEUE_DIR.glob("*.md"), reverse=True):
        text = path.read_text()
        draft = _parse_draft_markdown(text)
        if draft and draft.item_id == item_id:
            return path
    return None


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
    tmp = path.with_suffix(".tmp")
    tmp.write_text(_draft_markdown(draft))
    tmp.replace(path)
    return True


def skip_draft(item_id: str, skipped_dir: Path | None = None) -> bool:
    """Move a queued draft to a skipped folder (default: QUEUE_DIR/skipped).

    Returns True if a draft was moved. Idempotent: if already skipped, returns True.
    """
    path = _find_draft_path(item_id)
    if not path:
        return False
    skipped = skipped_dir or (QUEUE_DIR / "skipped")
    skipped.mkdir(parents=True, exist_ok=True)
    dest = skipped / path.name
    if dest.exists():
        # Idempotency: overwrite with the latest version
        path.replace(dest)
    else:
        path.rename(dest)
    return True
