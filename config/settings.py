"""Centralized, environment-aware settings."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.getenv("DATA_DIR", REPO_ROOT / "data")).expanduser()
RAW_DIR = DATA_DIR / "raw"
QUEUE_DIR = DATA_DIR / "queue"
NEWSLETTER_DIR = DATA_DIR / "newsletters"
REVIEW_DIR = DATA_DIR / "review"
ANALYSIS_DIR = DATA_DIR / "analysis"
DB_PATH = DATA_DIR / "content.db"
SOURCES_CSV = REPO_ROOT / "sources.csv"

# Supabase PostgreSQL backend (optional; falls back to local SQLite if not set)
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# LinkedIn auth (free API v2 products: Share on LinkedIn + Sign In with LinkedIn using OpenID Connect)
LINKEDIN_CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "")
LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "")
LINKEDIN_REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI", "http://localhost:8000/callback")
# Modern free scopes for personal posting
LINKEDIN_SCOPES = os.getenv("LINKEDIN_SCOPES", "openid profile email w_member_social").split()

# Token encryption (optional but recommended). Fernet needs a 32-byte base64 key.
TOKEN_SECRET = os.getenv("TOKEN_SECRET", "")

# LLM client settings (optional; rule-based drafting works without them)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")  # ollama | openai | anthropic
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")  # e.g. http://localhost:11434/v1 for Ollama
LLM_MODEL = os.getenv("LLM_MODEL", "llama3.2")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "30"))

# MCP server auth
MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "")

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
    for d in (DATA_DIR, RAW_DIR, QUEUE_DIR, NEWSLETTER_DIR, ANALYSIS_DIR, REVIEW_DIR):
        d.mkdir(parents=True, exist_ok=True)
