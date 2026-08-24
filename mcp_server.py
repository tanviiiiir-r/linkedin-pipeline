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

from config.settings import DATA_DIR, MCP_AUTH_TOKEN, QUEUE_DIR, REQUIRE_APPROVAL, ensure_dirs
from pipeline.approval import approve_draft, list_pending, list_ready_to_publish
from pipeline.drafting import Draft, save_draft
from pipeline.hermes import cmd_collect, cmd_draft, cmd_publish, cmd_score
from pipeline.publishers.linkedin import DirectLinkedInPublisher
from pipeline.storage import Item, init_db, list_items
from pipeline.tokens import has_tokens, load_tokens
from pipeline.youtube_draft import draft_from_youtube_url

mcp = FastMCP("linkedin-pipeline", host=os.getenv("FASTMCP_HOST", "127.0.0.1"), port=int(os.getenv("FASTMCP_PORT", "8000")))


def _require_auth(token: str) -> bool:
    """Return True if the request carries a valid bearer token (or auth is disabled)."""
    if not MCP_AUTH_TOKEN:
        return True
    if not token:
        return False
    parts = token.split()
    if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1] == MCP_AUTH_TOKEN:
        return True
    return token == MCP_AUTH_TOKEN


@mcp.tool()
def pipeline_status(auth_token: str = "") -> str:
    """Show pipeline health, data dir, and LinkedIn auth status. Requires MCP_AUTH_TOKEN if configured."""
    if not _require_auth(auth_token):
        return json.dumps({"ok": False, "error": "Unauthorized"}, indent=2)
    tokens = load_tokens()
    return json.dumps(
        {
            "ok": True,
            "data_dir": str(DATA_DIR),
            "approval_required": REQUIRE_APPROVAL,
            "linkedin_tokens_present": bool(tokens and tokens.get("access_token")),
            "linkedin_refresh_present": bool(tokens and tokens.get("refresh_token")),
            "linkedin_author_urn": tokens.get("author_urn") if tokens else None,
        },
        indent=2,
    )


@mcp.tool()
def collect_items(limit: int = 5, dry_run: bool = True, auth_token: str = "") -> str:
    """Collect items from all configured RSS and GitHub sources. Requires MCP_AUTH_TOKEN if configured.

    Args:
        limit: Max items per source.
        dry_run: If True, do not persist collected items to the database.
    """
    if not _require_auth(auth_token):
        return json.dumps({"ok": False, "error": "Unauthorized"})
    args = type("Args", (), {"limit": limit, "dry_run": dry_run})()
    cmd_collect(args)
    return f"Collection complete. Check {DATA_DIR / 'raw'} for saved items."


@mcp.tool()
def list_collected_items(status: str = "", limit: int = 20, auth_token: str = "") -> str:
    """List recently collected items, optionally filtered by status. Requires MCP_AUTH_TOKEN if configured."""
    if not _require_auth(auth_token):
        return json.dumps({"ok": False, "error": "Unauthorized"})
    init_db()
    items = list_items(status=status or None, limit=limit)
    return json.dumps([_item_to_dict(i) for i in items], indent=2)


@mcp.tool()
def score_items(limit: int = 50, min_confidence: int = 50, min_signal: int = 40, auth_token: str = "") -> str:
    """Score collected items against content pillars and mark worthy ones. Requires MCP_AUTH_TOKEN if configured."""
    if not _require_auth(auth_token):
        return json.dumps({"ok": False, "error": "Unauthorized"})
    args = type("Args", (), {"limit": limit, "min_confidence": min_confidence, "min_signal": min_signal, "dry_run": False})()
    cmd_score(args)
    return "Scoring complete."


@mcp.tool()
def list_worthy_items(limit: int = 20, auth_token: str = "") -> str:
    """List items marked as worthy after scoring. Requires MCP_AUTH_TOKEN if configured."""
    if not _require_auth(auth_token):
        return json.dumps({"ok": False, "error": "Unauthorized"})
    init_db()
    items = list_items(status="worthy", limit=limit)
    return json.dumps([_item_to_dict(i) for i in items], indent=2)


@mcp.tool()
def draft_posts(limit: int = 3, auth_token: str = "") -> str:
    """Draft LinkedIn posts and newsletter sections for worthy items. Requires MCP_AUTH_TOKEN if configured."""
    if not _require_auth(auth_token):
        return json.dumps({"ok": False, "error": "Unauthorized"})
    args = type("Args", (), {"limit": limit, "dry_run": False})()
    cmd_draft(args)
    return f"Drafts queued in {QUEUE_DIR}."


@mcp.tool()
def list_queue(auth_token: str = "") -> str:
    """List drafts awaiting approval and ready to publish. Requires MCP_AUTH_TOKEN if configured."""
    if not _require_auth(auth_token):
        return json.dumps({"ok": False, "error": "Unauthorized"})
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
def approve_draft_by_id(item_id: str, auth_token: str = "") -> str:
    """Approve a queued draft by its item_id. Human-in-the-loop gate. Requires MCP_AUTH_TOKEN if configured."""
    if not _require_auth(auth_token):
        return json.dumps({"ok": False, "error": "Unauthorized"})
    if approve_draft(item_id):
        return f"Approved draft {item_id}."
    return f"Draft {item_id} not found or already approved."


@mcp.tool()
def publish_approved_drafts(limit: int = 1, dry_run: bool = False, auth_token: str = "") -> str:
    """Publish approved drafts to LinkedIn. Requires stored tokens for real publish and MCP_AUTH_TOKEN if configured.

    Args:
        limit: Max drafts to publish.
        dry_run: If True, simulate publishing without calling LinkedIn.
    """
    if not _require_auth(auth_token):
        return json.dumps({"ok": False, "error": "Unauthorized"})
    args = type("Args", (), {"limit": limit, "dry_run": dry_run or not has_tokens(), "target": "linkedin"})()
    cmd_publish(args)
    return "Publish run complete."


@mcp.tool()
def generate_linkedin_auth_url(redirect_uri: str = "", auth_token: str = "") -> str:
    """Generate the LinkedIn OAuth URL for the operator to authorize the app. Requires MCP_AUTH_TOKEN if configured."""
    if not _require_auth(auth_token):
        return json.dumps({"ok": False, "error": "Unauthorized"})
    if redirect_uri:
        os.environ["LINKEDIN_REDIRECT_URI"] = redirect_uri
    from config.settings import LINKEDIN_CLIENT_ID

    if not LINKEDIN_CLIENT_ID:
        return "LINKEDIN_CLIENT_ID is not set."
    url = DirectLinkedInPublisher.authorization_url(state="hermes-mcp")
    return (
        "Open this URL in a browser and authorize the app:\n"
        f"{url}\n\n"
        "Then call exchange_linkedin_code with the code from the callback."
    )


@mcp.tool()
def exchange_linkedin_code(code: str, auth_token: str = "") -> str:
    """Exchange a LinkedIn OAuth authorization code for tokens and store them. Requires MCP_AUTH_TOKEN if configured."""
    if not _require_auth(auth_token):
        return json.dumps({"ok": False, "error": "Unauthorized"})
    from pipeline.hermes import cmd_linkedin_exchange

    args = type("Args", (), {"code": code})()
    result = cmd_linkedin_exchange(args)
    if result == 0:
        return "LinkedIn tokens saved successfully."
    return "LinkedIn token exchange failed. Check server logs."


@mcp.tool()
def get_linkedin_auth_status(auth_token: str = "") -> str:
    """Show whether LinkedIn tokens are stored and valid. Requires MCP_AUTH_TOKEN if configured."""
    if not _require_auth(auth_token):
        return json.dumps({"ok": False, "error": "Unauthorized"})
    tokens = load_tokens()
    return json.dumps(
        {
            "tokens_present": bool(tokens and tokens.get("access_token")),
            "refresh_token_present": bool(tokens and tokens.get("refresh_token")),
            "author_urn": tokens.get("author_urn") if tokens else None,
        },
        indent=2,
    )


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
def youtube_to_draft(url: str, dry_run: bool = False, auth_token: str = "") -> str:
    """Convert a YouTube URL into a LinkedIn draft and queue it. Requires MCP_AUTH_TOKEN if configured.

    Args:
        url: The YouTube video URL.
        dry_run: If True, return the draft JSON without saving it to the queue.
    """
    if not _require_auth(auth_token):
        return json.dumps({"ok": False, "error": "Unauthorized"})
    init_db()
    ensure_dirs()
    draft = draft_from_youtube_url(url)
    if not draft:
        return json.dumps({"ok": False, "error": f"Could not draft from URL: {url}"}, indent=2)
    if dry_run:
        return json.dumps({"ok": True, "draft": _draft_to_dict(draft)}, indent=2)
    return json.dumps({"ok": True, "item_id": draft.item_id, "message": "Draft queued."}, indent=2)


@mcp.tool()
def draft_today(limit: int = 1, dry_run: bool = False) -> str:
    """Draft today's post using the 7-day calendar and LLM humanizer.

    Args:
        limit: Number of draft candidates to produce.
        dry_run: If True, return the draft without saving it to the queue.
    """
    from config.calendar import day_plan
    from pipeline.calendar import select_for_today
    from pipeline.drafting_v2 import draft_item_v2
    from pipeline.storage import list_items

    init_db()
    ensure_dirs()
    plan = day_plan()
    candidates = list_items(status="worthy", limit=limit * 5)
    if not candidates:
        candidates = list_items(status=None, limit=limit * 5)
    if not candidates:
        return json.dumps({"ok": False, "error": "No items available. Run collect and score first."}, indent=2)

    selected, note = select_for_today(candidates, limit=limit)
    if not selected:
        return json.dumps(
            {"ok": False, "error": f"No strong signal for {plan.day_name} ({plan.post_type}). Run collect/plan-content or provide a manual item.", "note": note},
            indent=2,
        )
    drafts = []
    for item, score in selected:
        draft = draft_item_v2(item, score, day_plan=plan)
        drafts.append(draft)
        if not dry_run:
            save_draft(draft, QUEUE_DIR)
            from pipeline.storage import update_status
            update_status(item.item_url, "drafted")

    return json.dumps(
        {
            "ok": True,
            "day": plan.day_name,
            "post_type": plan.post_type,
            "count": len(drafts),
            "drafts": [
                {
                    "item_id": d.item_id,
                    "title": d.title,
                    "pillar": d.pillar,
                    "hashtags": d.hashtags,
                    "linkedin_post": d.linkedin_post,
                }
                for d in drafts
            ],
        },
        indent=2,
    )



if __name__ == "__main__":
    ensure_dirs()
    init_db()
    if MCP_AUTH_TOKEN:
        print("MCP auth token is configured; clients must pass it in tool arguments.", file=sys.stderr)
    # FastMCP 1.29+ reads host/port from FASTMCP_HOST / FASTMCP_PORT env vars;
    # host/port kwargs are no longer accepted.
    import os

    os.environ.setdefault("FASTMCP_HOST", "127.0.0.1")
    os.environ.setdefault("FASTMCP_PORT", "8000")
    mcp.run(transport="sse")
