"""Image generation for LinkedIn posts.

Economic provider chain:
1. Source article OpenGraph image (free, fast, relevant)
2. Provider-generated image (free Pollinations.ai by default; optional Fal AI)
3. Pexels free stock photo search (optional API key)
4. Text-only post if all image sources fail
"""
import html
import logging
import os
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

# Provider configuration
IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "pollinations").lower()
FAL_KEY = os.getenv("FAL_KEY", "")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

# Fal model alias (cheap + fast)
FAL_MODEL = os.getenv("FAL_MODEL", "fal-ai/flux/schnell")

IMAGE_DIR = DATA_DIR / "images"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_CANDIDATES_DIR = DATA_DIR / "image_candidates"
IMAGE_CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)

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


def _absolute_url(base: str, src: str) -> str | None:
    """Resolve a possibly-relative image src URL."""
    if not src:
        return None
    src = src.strip()
    if src.startswith(("http://", "https://")):
        return src
    if src.startswith("//"):
        return "https:" + src
    return urllib.parse.urljoin(base, src)


def _is_large_enough(img) -> bool:
    """Reject tiny icons, avatars, and tracking pixels."""
    try:
        w = int(img.get("width", "0").replace("px", "").strip() or 0)
        h = int(img.get("height", "0").replace("px", "").strip() or 0)
    except ValueError:
        w, h = 0, 0
    if w and h:
        return w >= 240 and h >= 120
    return True


def _download_image(url: str, output_path: Path) -> Path | None:
    """Download an image and convert webp to jpg for preview compatibility."""
    try:
        img_resp = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "image/webp,image/apng,image/*,*/*;q=0.8"},
        )
        img_resp.raise_for_status()
        content = img_resp.content
        if not content:
            return None
        output_path.write_bytes(content)
        if output_path.suffix.lower() == ".webp":
            try:
                jpg_path = output_path.with_suffix(".jpg")
                img = Image.open(output_path)
                img.convert("RGB").save(jpg_path, "JPEG")
                output_path.unlink()
                return jpg_path
            except (OSError, ValueError):
                logger.warning("Could not convert webp to jpg for %s", url)
        logger.info("Downloaded article image: %s", output_path)
        return output_path
    except (requests.RequestException, OSError):
        logger.exception("Image download failed: %s", url)
    return None


def extract_article_images(url: str, item_id: str, max_candidates: int = 4) -> list[str]:
    """Download OG + article body image candidates for a URL."""
    candidates_dir = IMAGE_CANDIDATES_DIR / item_id
    candidates_dir.mkdir(parents=True, exist_ok=True)
    found: list[str] = []
    try:
        page_resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        page_resp.raise_for_status()
        html_text = page_resp.text
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_text, "html.parser")

        og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"property": "og:image"})
        if og:
            img_url = og.get("content")
            abs_url = _absolute_url(url, img_url)
            if abs_url:
                path = _download_image(abs_url, candidates_dir / "og.jpg")
                if path:
                    found.append(str(path))

        if len(found) < max_candidates:
            tw = soup.find("meta", attrs={"name": "twitter:image"}) or soup.find("meta", property="twitter:image")
            if tw:
                img_url = tw.get("content")
                abs_url = _absolute_url(url, img_url)
                if abs_url:
                    path = _download_image(abs_url, candidates_dir / "twitter.jpg")
                    if path and str(path) not in found:
                        found.append(str(path))

        if len(found) < max_candidates:
            for tag in soup.select("article img, main img, .post-content img, .entry-content img"):
                if len(found) >= max_candidates:
                    break
                src = tag.get("src") or tag.get("data-src") or tag.get("data-lazy-src")
                abs_url = _absolute_url(url, src)
                if not abs_url:
                    continue
                if not _is_large_enough(tag):
                    continue
                suffix = Path(abs_url).suffix or ".jpg"
                suffix = suffix.split("?")[0] or ".jpg"
                if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
                    suffix = ".jpg"
                name = f"article_{len(found)}{suffix}"
                path = _download_image(abs_url, candidates_dir / name)
                if path and str(path) not in found:
                    found.append(str(path))
    except (requests.RequestException, OSError):
        logger.exception("Article image extraction failed for %s", url)
    return found


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
    except (requests.RequestException, OSError, ValueError):
        logger.exception("OG image fetch failed for %s", url)
    return None


def _save_response_image(resp: requests.Response, output_path: Path) -> Path | None:
    """Save image bytes from a response as PNG, converting if needed."""
    try:
        img = Image.open(BytesIO(resp.content))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(output_path, "PNG")
        return output_path
    except (OSError, ValueError):
        output_path.write_bytes(resp.content)
        return output_path


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
        _save_response_image(resp, output_path)
        logger.info("Downloaded image from Pollinations.ai: %s", output_path)
        return output_path
    except (requests.RequestException, OSError, ValueError):
        logger.exception("Pollinations.ai generation failed")
    return None


def _generate_with_fal(prompt: str, output_path: Path) -> Path | None:
    """Generate an image via Fal AI (requires FAL_KEY)."""
    if not FAL_KEY:
        logger.warning("FAL_KEY not set; skipping Fal AI generation")
        return None

    try:
        import fal_client

        handler = fal_client.submit(
            FAL_MODEL,
            arguments={
                "prompt": prompt,
                "image_size": "landscape_16_9",
                "num_inference_steps": 4,
            },
        )
        result = handler.get()
        images = result.get("images", [])
        if not images:
            logger.warning("Fal AI returned no images")
            return None
        img_url = images[0].get("url")
        if not img_url:
            logger.warning("Fal AI image URL missing")
            return None
        resp = requests.get(img_url, timeout=60)
        resp.raise_for_status()
        _save_response_image(resp, output_path)
        logger.info("Downloaded image from Fal AI: %s", output_path)
        return output_path
    except Exception:
        logger.exception("Fal AI generation failed")
    return None


def _generate_image(prompt: str, output_path: Path, provider: str, width: int = TARGET_WIDTH, height: int = TARGET_HEIGHT) -> Path | None:
    """Dispatch to the configured image generation provider."""
    if provider == "fal":
        return _generate_with_fal(prompt, output_path)
    if provider == "pollinations":
        return _generate_with_pollinations(prompt, output_path, width=width, height=height)
    logger.warning("Unknown image provider %s", provider)
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
            _save_response_image(img_resp, output_path)
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
    provider: str | None = None,
    item_id: str | None = None,
) -> tuple[Path | None, str]:
    """Return a local image path for the post, using the cheapest available source."""
    if not item_url:
        return None

    chosen_provider = provider or IMAGE_PROVIDER
    h = _slug(title) or _slug(item_url)
    output_path = IMAGE_DIR / f"{h}.png"
    if output_path.exists() and not skip_og:
        return output_path, "cache"

    # 1. Try OG image
    if not skip_og:
        og_path = output_path.with_suffix(".og.jpg")
        og = _fetch_og_image(item_url, og_path)
        if og:
            return og, "og"

    # 2. Try configured provider generation
    prompt = prompt_for_post(day, pillar, title, linkedin_post, hashtags)
    logger.info("Image prompt: %s", prompt)
    gen_path = output_path.with_suffix(f".{chosen_provider}.png")
    result = _generate_image(prompt, gen_path, chosen_provider, width=width, height=height)
    if result:
        return result, chosen_provider

    # 3. Try Pexels stock photo (if API key configured)
    pexels_query = _extract_pexels_query(day, pillar, title)
    pexels_path = output_path.with_suffix(".pexels.jpg")
    result = _search_pexels(pexels_query, pexels_path)
    if result:
        return result

    logger.warning("All image sources failed for %s", title)
    return None


def available_providers() -> list[str]:
    """Return the list of image providers that are currently usable."""
    providers = ["pollinations"]
    if FAL_KEY:
        providers.append("fal")
    if PEXELS_API_KEY:
        providers.append("pexels")
    return providers


if __name__ == "__main__":
    p, src = image_for_post(
        item_url="https://example.com/no-og-image-here",
        title="AI security red team visual",
        day="Friday",
        pillar="security_signal",
        linkedin_post="Google Cloud CISO on AI security fundamentals.",
        hashtags="#AISecurity",
        skip_og=False,
    )
    print("Generated:", p, "source:", src)
