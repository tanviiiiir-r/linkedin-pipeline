"""Image generation for LinkedIn posts.

Economic provider chain:
1. Source article OpenGraph image (free, fast, relevant)
2. Pollinations.ai free image generation (no API key)
3. Pexels free stock photo search (no API key, optional)
4. Text-only post if all image sources fail

RunPod/ComfyUI support is removed to avoid hourly GPU rental costs.
"""
import html
import logging
import re
import urllib.parse
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

from config.settings import DATA_DIR
from pipeline.log import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# Optional API keys (most providers below work without keys)
PEXELS_API_KEY = __import__("os").getenv("PEXELS_API_KEY", "")

IMAGE_DIR = DATA_DIR / "images"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

# Target LinkedIn feed aspect ratio ~1.91:1
TARGET_WIDTH = 1200
TARGET_HEIGHT = 627


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60]


def _clean_for_prompt(text: str) -> str:
    """Remove URLs, markdown, overly technical tokens, and keep only visual words."""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[#@]\w+", "", text)
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"\n+", ". ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()[:240]


def prompt_for_post(day: str, pillar: str, title: str, linkedin_post: str, hashtags: str) -> str:
    """Build a LinkedIn-optimized image prompt from post metadata."""
    base = _clean_for_prompt(title or linkedin_post)
    day_lower = day.lower()
    pillar_lower = pillar.lower()

    style_fragments = []
    if "tool" in pillar_lower or "monday" in day_lower:
        style_fragments.append("clean abstract SaaS product hero card, dark mode, single icon, minimal, 1.91:1 landscape")
    elif "viral" in pillar_lower or "tuesday" in day_lower:
        style_fragments.append("bold news-style editorial header, one strong visual metaphor, dynamic diagonal composition, glowing neural shapes, 1.91:1 landscape")
    elif "pattern" in pillar_lower or "wednesday" in day_lower:
        style_fragments.append("two connected panels with flowing data lines, inputs-to-output infographic, blue-purple gradient, 1.91:1 landscape")
    elif "builder" in pillar_lower or "thursday" in day_lower:
        style_fragments.append("cozy developer workspace, focused UI element with blurred screen glow, coffee cup, warm desk lighting, 1.91:1 landscape")
    elif "security" in pillar_lower or "friday" in day_lower:
        style_fragments.append("dark cybersecurity editorial header, abstract lock-shield geometry, red-team amber glow, 1.91:1 landscape")
    elif "founder" in pillar_lower or "saturday" in day_lower:
        style_fragments.append("strategic founder office scene, market-timing chart or whiteboard, soft natural light, back-or-side view, 1.91:1 landscape")
    elif "tomorrow" in pillar_lower or "sunday" in day_lower:
        style_fragments.append("wide futuristic horizon, dawn cityscape silhouette, glowing data streams in sky, one central symbol, 1.91:1 landscape")
    else:
        style_fragments.append("modern tech editorial illustration, clean composition, professional LinkedIn cover style, 1.91:1 landscape")

    style = ", ".join(style_fragments)

    entities = re.findall(r"\b(AWS|Google|OpenAI|Anthropic|Meta|Microsoft|NVIDIA|Pinterest|Cloudflare|Amazon|DeepMind|Gemini|Nvidia)\b", base)
    entity_clause = ""
    if entities:
        entity_clause = f" Inspired by {entities[0]} aesthetic but no logos, trademarks, or text."

    prompt = (
        f"Professional LinkedIn post header image about {base}. "
        f"{style}.{entity_clause} "
        "Completely free of text, letters, numbers, logos, watermarks, trademarks, UI chrome, and readable labels. "
        "High quality, centered composition, safe for business audience."
    )
    return prompt


def _fetch_og_image(url: str, output_path: Path) -> Path | None:
    """Try to download the source article's OpenGraph image."""
    try:
        page_resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        page_resp.raise_for_status()
        html_text = page_resp.text
        m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html_text, re.IGNORECASE)
        if not m:
            m = re.search(r'<meta[^>]+name="twitter:image"[^>]+content="([^"]+)"', html_text, re.IGNORECASE)
        if not m:
            return None
        img_url = html.unescape(m.group(1))
        img_resp = requests.get(img_url, timeout=20)
        img_resp.raise_for_status()
        try:
            img = Image.open(BytesIO(img_resp.content))
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(output_path, "PNG")
        except (OSError, ValueError):
            output_path.write_bytes(img_resp.content)
        logger.info("Downloaded OG image: %s", output_path)
        return output_path
    except Exception:
        logger.exception("OG image fetch failed for %s", url)
    return None


def _generate_with_pollinations(prompt: str, output_path: Path, width: int = TARGET_WIDTH, height: int = TARGET_HEIGHT) -> Path | None:
    """Generate an image via Pollinations.ai (free, no API key)."""
    encoded = urllib.parse.quote(prompt)
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width={width}&height={height}"
        f"&nologo=true"
        f"&negative_prompt=text,words,letters,numbers,logo,watermark,trademark,UI,labels,signature"
    )
    try:
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        if not resp.content or len(resp.content) < 1000:
            logger.warning("Pollinations returned empty/too-small response")
            return None
        # Pollinations returns JPEG; convert to PNG for consistency
        img = Image.open(BytesIO(resp.content))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(output_path, "PNG")
        logger.info("Downloaded image from Pollinations.ai: %s", output_path)
        return output_path
    except (requests.RequestException, OSError, ValueError):
        logger.exception("Pollinations.ai generation failed")
    return None


def _search_pexels(query: str, output_path: Path) -> Path | None:
    """Search Pexels for a free stock photo matching the query."""
    if not PEXELS_API_KEY:
        return None
    try:
        headers = {"Authorization": PEXELS_API_KEY}
        params = {"query": query, "per_page": 5, "orientation": "landscape"}
        resp = requests.get("https://api.pexels.com/v1/search", headers=headers, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        photos = data.get("photos", [])
        for photo in photos:
            src = photo.get("src", {}).get("large") or photo.get("src", {}).get("medium")
            if not src:
                continue
            img_resp = requests.get(src, timeout=20)
            img_resp.raise_for_status()
            try:
                img = Image.open(BytesIO(img_resp.content))
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                img.save(output_path, "PNG")
            except (OSError, ValueError):
                output_path.write_bytes(img_resp.content)
            logger.info("Downloaded image from Pexels: %s", output_path)
            return output_path
    except (requests.RequestException, OSError, ValueError, KeyError):
        logger.exception("Pexels search failed")
    return None


def _extract_pexels_query(day: str, pillar: str, title: str) -> str:
    """Create a simple search query for Pexels from post metadata."""
    if "security" in pillar.lower():
        return "cybersecurity technology dark"
    if "founder" in pillar.lower():
        return "business strategy office laptop"
    if "tool" in pillar.lower():
        return "software technology dashboard"
    if "builder" in pillar.lower():
        return "developer coding workspace"
    if "tomorrow" in pillar.lower():
        return "futuristic technology horizon"
    if "viral" in pillar.lower():
        return "technology innovation abstract"
    if "pattern" in pillar.lower():
        return "network technology abstract"
    return "technology abstract"


def image_for_post(
    item_url: str,
    title: str,
    day: str,
    pillar: str,
    linkedin_post: str,
    hashtags: str,
    width: int = TARGET_WIDTH,
    height: int = TARGET_HEIGHT,
    skip_og: bool = False,
) -> Path | None:
    """Return a local image path for the post, using the cheapest available source."""
    if not item_url:
        return None

    h = _slug(title) or _slug(item_url)
    output_path = IMAGE_DIR / f"{h}.png"
    if output_path.exists() and not skip_og:
        return output_path

    # 1. Try OG image
    if not skip_og:
        og_path = output_path.with_suffix(".og.jpg")
        og = _fetch_og_image(item_url, og_path)
        if og:
            return og

    # 2. Try Pollinations.ai free generation
    prompt = prompt_for_post(day, pillar, title, linkedin_post, hashtags)
    logger.info("Image prompt: %s", prompt)
    gen_path = output_path.with_suffix(".gen.png")
    result = _generate_with_pollinations(prompt, gen_path, width=width, height=height)
    if result:
        return result

    # 3. Try Pexels stock photo (if API key configured)
    pexels_query = _extract_pexels_query(day, pillar, title)
    pexels_path = output_path.with_suffix(".pexels.jpg")
    result = _search_pexels(pexels_query, pexels_path)
    if result:
        return result

    logger.warning("All image sources failed for %s", title)
    return None


if __name__ == "__main__":
    p = image_for_post(
        item_url="https://example.com/no-og-image-here",
        title="AI security red team visual",
        day="Friday",
        pillar="security_signal",
        linkedin_post="Google Cloud CISO on AI security fundamentals.",
        hashtags="#AISecurity",
        skip_og=False,
    )
    print("Generated:", p)
