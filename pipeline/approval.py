"""Human-in-the-loop approval queue."""
import shutil
from pathlib import Path

from pipeline.drafting import Draft, _draft_markdown, _parse_draft_markdown, load_drafts
from config.settings import QUEUE_DIR


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
