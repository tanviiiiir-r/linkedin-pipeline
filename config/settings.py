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
PLANNED_DIR = DATA_DIR / "planned"
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
    "api", "tool", "framework", "llm", "rag",
]

# Terms that are evergreen but easily look fresh when old content is recycled.
# The scorer demotes them unless the item is genuinely recent (see scoring.py).
STALE_EVERGREEN_TERMS = ["mcp"]

PILLARS = ["tool_drop", "viral_explained", "pattern_spotting", "builder_memo", "tomorrow_in_ai"]

# Human-in-the-loop: require explicit approval before any publish
REQUIRE_APPROVAL = os.getenv("REQUIRE_APPROVAL", "true").lower() in ("1", "true", "yes")

# Recency policy: freshness-first selection with planned-evergreen fallback.
# Anything older than the source max age is rejected at collection time.
# Breaking items get an exponential age penalty after AGE_PENALTY_START_HOURS.
RECENCY_POLICY = {
    "breaking_max_age_hours": int(os.getenv("BREAKING_MAX_AGE_HOURS", "48")),
    "planned_half_life_hours": int(os.getenv("PLANNED_HALF_LIFE_HOURS", "168")),
    "age_penalty_start_hours": int(os.getenv("AGE_PENALTY_START_HOURS", "24")),
    "selection_threshold": int(os.getenv("SELECTION_THRESHOLD", "55")),
    "source_max_age_hours": {
        "rss": int(os.getenv("RSS_MAX_AGE_HOURS", "72")),
        "reddit": int(os.getenv("REDDIT_MAX_AGE_HOURS", "48")),
        "youtube": int(os.getenv("YOUTUBE_MAX_AGE_HOURS", "72")),
        "instagram": int(os.getenv("INSTAGRAM_MAX_AGE_HOURS", "48")),
        "github-trending": int(os.getenv("GITHUB_TRENDING_MAX_AGE_HOURS", "72")),
        "github-search": int(os.getenv("GITHUB_SEARCH_MAX_AGE_HOURS", "72")),
    },
    "engagement_floors": {
        "reddit": {"score": int(os.getenv("REDDIT_MIN_SCORE", "30")), "comments": int(os.getenv("REDDIT_MIN_COMMENTS", "10"))},
        "youtube": {"subscribers": 0},  # not available via Composio; placeholder
        "github-search": {"stars_per_day": float(os.getenv("GITHUB_MIN_STARS_PER_DAY", "5.0"))},
        "github-trending": {"is_trending": True},
    },
}


def ensure_dirs():
    for d in (DATA_DIR, RAW_DIR, QUEUE_DIR, NEWSLETTER_DIR, ANALYSIS_DIR, REVIEW_DIR, PLANNED_DIR):
        d.mkdir(parents=True, exist_ok=True)
