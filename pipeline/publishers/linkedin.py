"""LinkedIn publishing adapters: direct OAuth v2 (free personal API) + safe dry-run."""
import logging

import requests

from config.settings import (
    LINKEDIN_CLIENT_ID,
    LINKEDIN_CLIENT_SECRET,
    LINKEDIN_REDIRECT_URI,
    LINKEDIN_SCOPES,
    REQUIRE_APPROVAL,
)
from pipeline.drafting import Draft
from pipeline.tokens import load_tokens, save_tokens

logger = logging.getLogger(__name__)


class LinkedInPublisher:
    """Abstract publisher interface."""

    def is_configured(self) -> bool:
        raise NotImplementedError

    def publish(self, draft: Draft) -> dict:
        raise NotImplementedError


class DryRunPublisher(LinkedInPublisher):
    """Safe fallback when no LinkedIn credentials are configured."""

    def is_configured(self) -> bool:
        return True

    def publish(self, draft: Draft) -> dict:
        if REQUIRE_APPROVAL and not draft.approved:
            return {"ok": False, "error": "Draft not approved by human"}
        return {
            "ok": True,
            "dry_run": True,
            "approval_required": REQUIRE_APPROVAL,
            "post": draft.linkedin_post,
            "hashtags": draft.hashtags,
            "source_url": draft.source_url,
        }


class DirectLinkedInPublisher(LinkedInPublisher):
    """Publish via free LinkedIn API v2 using personal OAuth 2.0 tokens."""

    BASE_URL = "https://api.linkedin.com/v2"
    AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
    TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"

    def __init__(
        self,
        access_token: str | None = None,
        refresh_token: str | None = None,
        author_urn: str | None = None,
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.author_urn = author_urn

    def is_configured(self) -> bool:
        return bool(self.access_token and self.author_urn)

    @classmethod
    def authorization_url(cls, state: str = "hermes") -> str:
        """Build the LinkedIn OAuth authorization URL for the free products."""
        if not LINKEDIN_CLIENT_ID or not LINKEDIN_REDIRECT_URI:
            raise RuntimeError(
                "LINKEDIN_CLIENT_ID and LINKEDIN_REDIRECT_URI must be set"
            )
        scopes = "%20".join(LINKEDIN_SCOPES)
        return (
            f"{cls.AUTH_URL}"
            f"?response_type=code"
            f"&client_id={LINKEDIN_CLIENT_ID}"
            f"&redirect_uri={LINKEDIN_REDIRECT_URI}"
            f"&state={state}"
            f"&scope={scopes}"
        )

    @classmethod
    def exchange_code(cls, code: str) -> dict:
        """Exchange authorization code for access + refresh tokens."""
        if not (LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET and LINKEDIN_REDIRECT_URI):
            raise RuntimeError("LinkedIn OAuth credentials are incomplete")
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": LINKEDIN_CLIENT_ID,
            "client_secret": LINKEDIN_CLIENT_SECRET,
            "redirect_uri": LINKEDIN_REDIRECT_URI,
        }
        r = requests.post(cls.TOKEN_URL, data=payload, timeout=30)
        r.raise_for_status()
        return r.json()

    @classmethod
    def refresh_access_token(cls, refresh_token: str) -> dict:
        """Refresh a short-lived access token using the refresh token."""
        if not (LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET):
            raise RuntimeError("LinkedIn client credentials are incomplete")
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": LINKEDIN_CLIENT_ID,
            "client_secret": LINKEDIN_CLIENT_SECRET,
        }
        r = requests.post(cls.TOKEN_URL, data=payload, timeout=30)
        r.raise_for_status()
        return r.json()

    def fetch_author_urn(self) -> str | None:
        """Fetch the authenticated member's person URN using the userinfo endpoint."""
        if not self.access_token:
            return None
        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            r = requests.get(
                "https://api.linkedin.com/v2/userinfo",
                headers=headers,
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            # OpenID userinfo returns 'sub' which is the member id
            member_id = data.get("sub")
            if member_id:
                return f"urn:li:person:{member_id}"
            logger.warning("LinkedIn userinfo did not return a member id (sub)")
        except requests.RequestException:
            logger.exception("Failed to fetch LinkedIn author URN")
        return None

    def ensure_fresh_token(self) -> bool:
        """Refresh access token if a refresh token is available, then persist."""
        if not self.refresh_token:
            return False
        try:
            resp = self.refresh_access_token(self.refresh_token)
            self.access_token = resp.get("access_token", self.access_token)
            if "refresh_token" in resp:
                self.refresh_token = resp["refresh_token"]
            author_urn = self.author_urn or self.fetch_author_urn()
            save_tokens(
                self.access_token,
                self.refresh_token,
                resp.get("expires_in", 0),
                author_urn or "",
            )
            return True
        except Exception:
            logger.exception("Failed to refresh LinkedIn access token")
            return False

    def publish(self, draft: Draft) -> dict:
        if REQUIRE_APPROVAL and not draft.approved:
            return {"ok": False, "error": "Draft not approved by human"}
        if not self.access_token:
            return {"ok": False, "error": "Missing LinkedIn access token"}

        # Try to refresh if we have a refresh token
        self.ensure_fresh_token()

        if not self.author_urn:
            self.author_urn = self.fetch_author_urn()
            if not self.author_urn:
                return {"ok": False, "error": "Could not determine LinkedIn author URN"}
            # Persist the URN so we don't fetch it every time
            save_tokens(
                self.access_token,
                self.refresh_token or "",
                0,
                self.author_urn,
            )

        url = f"{self.BASE_URL}/ugcPosts"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }
        payload = {
            "author": self.author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": draft.linkedin_post},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=30)
            r.raise_for_status()
            return {"ok": True, "platform": "linkedin", "response": r.json()}
        except requests.RequestException as e:
            logger.exception("LinkedIn publish failed")
            return {
                "ok": False,
                "error": str(e),
                "response": getattr(e.response, "text", ""),
            }


def get_publisher() -> LinkedInPublisher:
    """Factory: prefer stored direct OAuth tokens, otherwise fall back to dry-run."""
    tokens = load_tokens()
    if tokens and tokens.get("access_token"):
        return DirectLinkedInPublisher(
            access_token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
            author_urn=tokens.get("author_urn"),
        )
    return DryRunPublisher()
