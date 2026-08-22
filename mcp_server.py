"""MCP server exposing the LinkedIn pipeline as agent tools.

Run with:
    python mcp_server.py

Then register with Claude Code:
    claude mcp add --transport sse linkedin-pipeline http://localhost:8000/sse
"""
import json
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Ensure repo root is importable when run directly
REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.settings import DATA_DIR, QUEUE_DIR, REQUIRE_APPROVAL, ensure_dirs
from pipeline.approval import approve_draft, list_pending, list_ready_to_publish
from pipeline.drafting import Draft, draft_item, load_drafts, save_draft
from pipeline.hermes import cmd_collect, cmd_draft, cmd_publish, cmd_queue, cmd_score
from pipeline.publishers.linkedin import DirectLinkedInPublisher, get_publisher
from pipeline.scoring import ScoreResult, score_item
from pipeline.storage import Item, init_db, list_items, load_item
from pipeline.tokens import has_tokens, load_tokens

mcp = FastMCP("linkedin-pipeline")


def _collect_args(limit: int = 5, dry_run: bool = True):
    class Args:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    return Args(limit=limit, dry_run=dry_run)


def _item_to_dict(item: Item) -> dict:
    return json.loads(item.model_dump_json())


def _draft_to_dict(draft: Draft) -> dict:
    return {
        "item_id": draft.item_id,
        "pillar": draft.pillar,
        "approved": draft.approved,
        "published": draft.published,
        "hashtags": draft.hashtags,
        "source_url": draft.source_url,
        "created_at": draft.created_at,
        "linkedin_post": draft.linkedin_post,
        "newsletter_section": draft.newsletter_section,
    }


@mcp.tool()
def pipeline_status() -> str:
    """Show pipeline health, data dir, and LinkedIn auth status."""
    tokens = load_tokens()
    return json.dumps(
        {
            "data_dir": str(DATA_DIR),
            "approval_required": REQUIRE_APPROVAL,
            "linkedin_tokens_present": bool(tokens and tokens.get("access_token")),
            "linkedin_refresh_present": bool(tokens and tokens.get("refresh_token")),
            "linkedin_author_urn": tokens.get("author_urn") if tokens else None,
        },
        indent=2,
    )


@mcp.tool()
def collect_items(limit: int = 5, dry_run: bool = True) -> str:
    """Collect items from all configured RSS and GitHub sources.

    Args:
        limit: Max items per source.
        dry_run: If True, do not persist collected items to the database.
    """
    args = _collect_args(limit=limit, dry_run=dry_run)
    cmd_collect(args)
    return f"Collection complete. Check {DATA_DIR / 'raw'} for saved items."


@mcp.tool()
def list_collected_items(status: str = "", limit: int = 20) -> str:
    """List recently collected items, optionally filtered by status."""
    init_db()
    items = list_items(status=status or None, limit=limit)
    return json.dumps([_item_to_dict(i) for i in items], indent=2)


@mcp.tool()
def score_items(limit: int = 50, min_confidence: int = 50, min_signal: int = 40) -> str:
    """Score collected items against content pillars and mark worthy ones."""
    args = _collect_args(limit=limit)
    args.min_confidence = min_confidence
    args.min_signal = min_signal
    cmd_score(args)
    return "Scoring complete."


@mcp.tool()
def list_worthy_items(limit: int = 20) -> str:
    """List items marked as worthy after scoring."""
    init_db()
    items = list_items(status="worthy", limit=limit)
    return json.dumps([_item_to_dict(i) for i in items], indent=2)


@mcp.tool()
def draft_posts(limit: int = 3) -> str:
    """Draft LinkedIn posts and newsletter sections for worthy items."""
    args = _collect_args(limit=limit)
    cmd_draft(args)
    return f"Drafts queued in {QUEUE_DIR}."


@mcp.tool()
def list_queue() -> str:
    """List drafts awaiting approval and ready to publish."""
    pending = list_pending()
    ready = list_ready_to_publish()
    return json.dumps(
        {
            "pending_approval": [_draft_to_dict(d) for d in pending],
            "ready_to_publish": [_draft_to_dict(d) for d in ready],
        },
        indent=2,
    )


@mcp.tool()
def approve_draft_by_id(item_id: str) -> str:
    """Approve a queued draft by its item_id. Human-in-the-loop gate."""
    if approve_draft(item_id):
        return f"Approved draft {item_id}."
    return f"Draft {item_id} not found or already approved."


@mcp.tool()
def publish_approved_drafts(limit: int = 1, dry_run: bool = False) -> str:
    """Publish approved drafts to LinkedIn. Requires stored tokens for real publish.

    Args:
        limit: Max drafts to publish.
        dry_run: If True, simulate publishing without calling LinkedIn.
    """
    args = _collect_args(limit=limit)
    args.dry_run = dry_run or not has_tokens()
    cmd_publish(args)
    return "Publish run complete."


@mcp.tool()
def generate_linkedin_auth_url(redirect_uri: str = "") -> str:
    """Generate the LinkedIn OAuth URL for the operator to authorize the app."""
    if redirect_uri:
        os.environ["LINKEDIN_REDIRECT_URI"] = redirect_uri
    from config.settings import LINKEDIN_CLIENT_ID, LINKEDIN_REDIRECT_URI

    if not LINKEDIN_CLIENT_ID:
        return "LINKEDIN_CLIENT_ID is not set."
    url = DirectLinkedInPublisher.authorization_url(state="hermes-mcp")
    return f"Open this URL in a browser and authorize the app:\n{url}\n\nThen call exchange_linkedin_code with the code from the callback."


@mcp.tool()
def exchange_linkedin_code(code: str) -> str:
    """Exchange a LinkedIn OAuth authorization code for tokens and store them."""
    try:
        resp = DirectLinkedInPublisher.exchange_code(code)
    except Exception as e:
        return f"Token exchange failed: {e}"

    access_token = resp.get("access_token")
    refresh_token = resp.get("refresh_token", "")
    expires_in = resp.get("expires_in", 0)
    if not access_token:
        return "No access_token in LinkedIn response."

    pub = DirectLinkedInPublisher(access_token=access_token, author_urn="")
    author_urn = pub.fetch_author_urn()
    from pipeline.tokens import save_tokens

    save_tokens(access_token, refresh_token, expires_in, author_urn or "")
    return f"LinkedIn tokens saved. Author URN: {author_urn or 'not resolved yet'}."


@mcp.tool()
def get_linkedin_auth_status() -> str:
    """Show whether LinkedIn tokens are stored and valid."""
    tokens = load_tokens()
    return json.dumps(
        {
            "tokens_present": bool(tokens and tokens.get("access_token")),
            "refresh_token_present": bool(tokens and tokens.get("refresh_token")),
            "author_urn": tokens.get("author_urn") if tokens else None,
        },
        indent=2,
    )


if __name__ == "__main__":
    ensure_dirs()
    init_db()
    mcp.run(transport="sse", host="127.0.0.1", port=8000)
