"""Centralized, environment-aware settings."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.getenv("DATA_DIR", REPO_ROOT / "data")).expanduser()
RAW_DIR = DATA_DIR / "raw"
QUEUE_DIR = DATA_DIR / "queue"
DB_PATH = DATA_DIR / "content.db"

# LinkedIn auth (free API v2 products: Share on LinkedIn + Sign In with LinkedIn using OpenID Connect)
LINKEDIN_CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "")
LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "")
LINKEDIN_REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI", "http://localhost:8000/callback")
# Modern free scopes for personal posting
LINKEDIN_SCOPES = os.getenv("LINKEDIN_SCOPES", "openid profile email w_member_social").split()

# Token encryption (optional but recommended). Fernet needs a 32-byte base64 key.
TOKEN_SECRET = os.getenv("TOKEN_SECRET", "")

# Collection
MAX_RAW_CHARS = 3000
CLAIM_KEYWORDS = [
    "released", "launched", "announced", "introduces", "new",
    "model", "agent", "vulnerability", "attack", "benchmark",
    "api", "tool", "framework", "llm", "mcp", "rag",
]

PILLARS = ["tool_drop", "viral_explained", "pattern_spotting", "builder_memo", "tomorrow_in_ai"]

# Human-in-the-loop: require explicit approval before any publish
REQUIRE_APPROVAL = os.getenv("REQUIRE_APPROVAL", "true").lower() in ("1", "true", "yes")


def ensure_dirs():
    for d in (DATA_DIR, RAW_DIR, QUEUE_DIR):
        d.mkdir(parents=True, exist_ok=True)
