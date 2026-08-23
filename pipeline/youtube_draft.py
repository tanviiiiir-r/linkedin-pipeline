"""YouTube URL → Item → draft using title/description/captions and an LLM.

If the optional `youtube_transcript_api` package is installed, it will fetch
captions. Otherwise we fall back to the video description and title.
"""
import html
import json
import logging
import re

logger = logging.getLogger(__name__)
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import requests

from pipeline.drafting import Draft, save_draft
from pipeline.llm_client import draft_from_summary, summarize_text
from pipeline.scoring import ScoreResult, score_item
from pipeline.storage import Item, item_exists, save_item
from pipeline.topics import extract_topics


def _video_id(url: str) -> str | None:
    """Extract YouTube video id from a URL."""
    parsed = urlparse(url)
    if parsed.hostname in {"youtu.be", "www.youtu.be", "youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.hostname == "youtu.be" or parsed.path.startswith("/shorts/"):
            return parsed.path.strip("/").split("/")[-1]
        qs = parse_qs(parsed.query)
        v = qs.get("v")
        if v:
            return v[0]
    return None


def _fetch_page(video_id: str) -> dict:
    """Fetch the YouTube watch page and extract basic metadata."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    text = resp.text

    title_match = re.search(r'"title":"([^"]{5,200})",(?:"title":|"lengthSeconds")', text)
    title = html.unescape(title_match.group(1)) if title_match else "Untitled YouTube video"

    # Try to find the video description in the initial JSON data
    desc = ""
    desc_match = re.search(r'"shortDescription":"([^"]*)"', text)
    if desc_match:
        desc = html.unescape(desc_match.group(1))

    # Try to locate caption tracks in the embedded ytInitialPlayerResponse JSON.
    captions = []
    cap_match = re.search(r'"captionTracks":(\[[^\]]+\])', text)
    if cap_match:
        try:
            tracks = json.loads(cap_match.group(1))
            for track in tracks:
                base = track.get("baseUrl")
                lang = track.get("languageCode", "")
                if base and lang.startswith("en"):
                    captions.append(base)
        except Exception:
            logger.debug("Failed to parse caption track: %s", url, exc_info=True)

    return {"title": title, "description": desc, "caption_urls": captions}


def _fetch_caption_xml(url: str) -> str:
    """Fetch a caption track and strip XML tags to return plain text."""
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        text = re.sub(r"<[^>]+>", " ", resp.text)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text
    except Exception:
        logger.warning("Caption XML fetch failed for %s", url, exc_info=True)
        return ""


def _transcript(video_id: str) -> str:
    """Best-effort transcript extraction with multiple fallbacks."""
    # Prefer youtube_transcript_api if installed.
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        snippets = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "en-US", "en-GB"])
        return " ".join(s.get("text", "") for s in snippets)
    except Exception:
        logger.warning("Transcript fetch failed for %s", video_id, exc_info=True)

    page = _fetch_page(video_id)
    for cap_url in page.get("caption_urls", []):
        text = _fetch_caption_xml(cap_url)
        if text:
            return text
    return ""


def item_from_youtube_url(url: str) -> Item | None:
    """Create or load a pipeline Item for a YouTube URL."""
    video_id = _video_id(url)
    if not video_id:
        return None
    canonical_url = f"https://www.youtube.com/watch?v={video_id}"
    if item_exists(canonical_url):
        from pipeline.storage import load_item
        return load_item(canonical_url)

    transcript = _transcript(video_id)
    page = _fetch_page(video_id)
    title = page.get("title", "Untitled YouTube video")
    description = page.get("description", "")

    raw = transcript or description
    if not raw.strip():
        raw = title

    summary = transcript[:800] if transcript else description[:800]
    claims = [description[:240]] if description else [title]

    item = Item(
        source_name="YouTube (manual)",
        source_url=canonical_url,
        item_url=canonical_url,
        item_title=title,
        item_author="",
        published_at=datetime.now(timezone.utc).isoformat(),
        source_type="youtube",
        content_type="video",
        summary=summary,
        key_claims=claims,
        raw_content=raw[:3000],
    )
    save_item(item)
    return item


def draft_from_youtube_url(url: str) -> Draft | None:
    """Generate a LinkedIn draft for a YouTube URL and save it to the queue."""
    item = item_from_youtube_url(url)
    if not item:
        return None

    score = score_item(item)
    # Force a pillar so every manual YouTube URL can become a draft even if
    # rule-based scoring is conservative.
    if not score.pillar:
        score.pillar = "viral_explained"
        score.pillar_confidence = max(score.pillar_confidence, 55)
        score.signal_strength = max(score.signal_strength, 45)

    # If an LLM is available, use it; otherwise fall back to rule-based draft.
    if _llm_usable():
        summary = summarize_text(item.raw_content, max_words=120)
        generated = draft_from_summary(item.item_title, summary, item.item_url)
        draft = _build_draft_from_llm(item, score, generated)
    else:
        draft = draft_item(item, score)

    return save_draft(draft, queue_dir=None)


def _llm_usable() -> bool:
    from pipeline.llm_client import is_available

    return is_available()


def _build_draft_from_llm(item: Item, score: ScoreResult, generated: dict) -> Draft:
    from pipeline.drafting import Draft
    from pipeline.topics import hashtags_from_topics

    return Draft(
        item_id=item.id,
        pillar=score.pillar or "viral_explained",
        title=item.item_title,
        source_url=item.item_url,
        created_at=datetime.now(timezone.utc).isoformat(),
        linkedin_post=generated.get("linkedin_post", ""),
        newsletter_section=generated.get("newsletter_section", ""),
        short_pill=generated.get("short_pill", ""),
        forward_pill=generated.get("forward_pill", ""),
        narrative_pill=generated.get("narrative_pill", ""),
        hashtags=generated.get("hashtags") or hashtags_from_topics(score.topics or extract_topics(item.raw_content)),
    )


# Import at bottom to avoid circular imports at module load time.
from pipeline.drafting import draft_item
