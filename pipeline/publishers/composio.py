"""Composio-based publishers for LinkedIn and Twitter/X.

These call the Composio CLI to execute connected-app actions. They require:
- composio CLI installed and authenticated
- A connected LinkedIn account (word_id/connection ACTIVE)
- A connected Twitter/X account (word_id/connection ACTIVE)

No API keys for the platforms themselves are stored; Composio holds the OAuth.
"""
import json
import logging
import shutil
import subprocess  # nosec B404
from pathlib import Path

from config.settings import REQUIRE_APPROVAL
from pipeline.drafting import Draft
from pipeline.publishers.linkedin import LinkedInPublisher

logger = logging.getLogger(__name__)


def _composio_bin() -> str | None:
    """Return the absolute path to the composio CLI, or None if unavailable."""
    candidate = shutil.which("composio")
    if candidate:
        return candidate
    alt = Path("/opt/data/home/.local/bin/composio")
    if alt.is_file():
        return str(alt)
    return None


def _run(slug: str, payload: dict, dry_run: bool = False, account: str = "") -> dict:
    """Execute a Composio tool via the CLI and return the response dict."""
    binary = _composio_bin()
    if not binary:
        return {"ok": False, "error": "composio CLI not found on PATH"}

    cmd = [binary, "execute", slug]
    if dry_run:
        cmd.append("--dry-run")
    if account:
        cmd.extend(["--account", account])
    cmd.extend(["-d", json.dumps(payload)])

    try:
        result = subprocess.run(  # nosec B603
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "composio execute timed out"}
    except OSError as e:
        logger.exception("Failed to execute composio command")
        return {"ok": False, "error": f"composio execute failed: {e}"}

    # Composio returns {"successful": bool, ...} or an error object
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError:
        data = {"raw_stdout": result.stdout, "raw_stderr": result.stderr}

    successful = bool(data.get("successful", result.returncode == 0))
    if not successful:
        error_msg = result.stderr.strip() or data.get("error") or "composio execute failed"
        return {"ok": False, "error": error_msg, **data}

    return {"ok": True, **data}


class ComposioLinkedInPublisher(LinkedInPublisher):
    """Publish approved drafts to LinkedIn via Composio's connected account."""

    def __init__(self, author_urn: str | None = None, account: str = ""):
        self.author_urn = author_urn
        self.account = account
        self._resolved_author: str | None = None

    def is_configured(self) -> bool:
        return _composio_bin() is not None

    def _resolve_author(self) -> str | None:
        if self._resolved_author:
            return self._resolved_author
        if self.author_urn:
            self._resolved_author = self.author_urn
            return self._resolved_author

        # Fetch the authenticated member's person URN via Composio
        resp = _run("LINKEDIN_GET_MY_INFO", {}, account=self.account)
        if not resp.get("ok"):
            logger.warning("Composio LinkedIn author resolution failed: %s", resp.get("error"))
            return None

        # Composio returns the LinkedIn response nested; find the person URN
        person_urn = None
        for key in ("sub", "id"):
            if key in resp:
                person_urn = resp[key]
                break

        # Try nested response data if not found at top level
        if not person_urn:
            data = resp.get("data", resp)
            for key in ("sub", "id"):
                if key in data:
                    person_urn = data[key]
                    break

        if person_urn and not str(person_urn).startswith("urn:li:"):
            person_urn = f"urn:li:person:{person_urn}"

        self._resolved_author = person_urn
        return person_urn

    def publish(self, draft: Draft) -> dict:
        if REQUIRE_APPROVAL and not draft.approved:
            return {"ok": False, "error": "Draft not approved by human"}

        author = self._resolve_author()
        if not author:
            return {"ok": False, "error": "Could not resolve LinkedIn author URN via Composio"}

        commentary = draft.linkedin_post[:3000]
        payload = {
            "author": author,
            "commentary": commentary,
            "visibility": "PUBLIC",
        }
        return _run("LINKEDIN_CREATE_LINKED_IN_POST", payload, account=self.account)


class ComposioTwitterPublisher(LinkedInPublisher):
    """Publish approved drafts to Twitter/X via Composio's connected account."""

    def __init__(self, account: str = ""):
        self.account = account

    def is_configured(self) -> bool:
        return _composio_bin() is not None

    def publish(self, draft: Draft) -> dict:
        if REQUIRE_APPROVAL and not draft.approved:
            return {"ok": False, "error": "Draft not approved by human"}

        # X limit is 280 weighted chars for basic; trim aggressively
        text = draft.linkedin_post[:280]
        payload = {"text": text}
        return _run("TWITTER_CREATION_OF_A_POST", payload, account=self.account)


def get_composio_linkedin_publisher() -> ComposioLinkedInPublisher | None:
    if not _composio_bin():
        return None
    return ComposioLinkedInPublisher()


def get_composio_twitter_publisher() -> ComposioTwitterPublisher | None:
    if not _composio_bin():
        return None
    return ComposioTwitterPublisher()
