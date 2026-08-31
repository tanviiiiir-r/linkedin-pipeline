"""Image generation for LinkedIn posts.

Candidate policy:
- Up to 2 non-AI candidates: article OpenGraph/Twitter/body images, plus Unsplash fallback.
- Up to 2 AI-generated candidates from different angles (environment, message, focus, POV).
- Dashboard lets the operator preview all 4 and select the active image for posting.
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

# Candidate policy: 2 non-AI (OG/stock) + 2 AI generated from different angles
NON_AI_CANDIDATES = 2
AI_CANDIDATES = 2
MIN_USABLE_WIDTH = 400
MIN_USABLE_HEIGHT = 200

# Target LinkedIn feed aspect ratio ~1.91:1
TARGET_WIDTH = 1200
TARGET_HEIGHT = 627


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60]


def _clean_for_prompt(text: str, max_len: int = 240) -> str:
    """Remove URLs, markdown, overly technical tokens, and keep only visual words."""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[#@]\w+", "", text)
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"\n+", ". ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()[:max_len]



def _extract_visual_keywords(title: str, linkedin_post: str, hashtags: str, source_url: str = "") -> tuple[str, str]:
    """Extract a concrete visual subject and a short keyword list from the post."""
    clean_title = _clean_for_prompt(title, max_len=160)
    clean_post = _clean_for_prompt(linkedin_post, max_len=500)
    clean_hashtags = _clean_for_prompt(hashtags or "", max_len=120)
    text = f"{clean_title} {clean_post} {clean_hashtags}"

    topic_re = re.compile(
        r"\b(?:"
        r"multi[- ]?agent|agentic|coding|red[- ]?team|jailbreak|safety|security|cyber|harness|"
        r"tokeniz|embedd|fine[- ]?tun|post[- ]?train|RL|scaling|inference|deployment|"
        r"orchestrat|delegat|routing|least[- ]?privilege|data center|workspace|server|cloud|"
        r"abstract|conceptual|developer|builder|startup|founder|strategy|horizon|future|"
        r"model|architecture|benchmark|evaluation|research|paper|startup|product|framework|"
        r"api|platform|infrastructure|gpu|compute|memory|attention|transformer|agent|llm|"
        r"language model|reasoning|planning|code generation|machine learning|deep learning|"
        r"neural network|fine tuning|pre[- ]?train|dataset|synthetic|simulation|automation|"
        r"interface|workflow|pipeline|production|deployment|engineering|software|hardware|"
        r"chip|processor|datacenter|cloud|edge|server|robot|drone|autonomous|vision|"
        r"nlp|text|chatbot|assistant|tool|library|sdk|repo|github|open source|"
        r"vulnerability|exploit|attack|threat|malware|cve|payload|sandbox|mitigation|"
        r"privacy|compliance|governance|risk|audit|cryptography|encryption"
        r")[a-z]*\b",
        re.IGNORECASE,
    )
    topics = sorted({t.lower().rstrip('s') for t in topic_re.findall(text)})
    if not topics:
        topics = ["technology"]
    # Keep up to 5
    keywords = ", ".join(topics[:5])

    # Domain hint (only for non-generic hosts; appended so it does not dominate topic)
    domain = ""
    if source_url:
        try:
            from urllib.parse import urlparse
            host = urlparse(source_url).netloc.replace("www.", "").split(".")[0]
            generic_hosts = {"reddit", "youtube", "arxiv", "medium", "substack", "github"}
            if host and host not in generic_hosts and host not in topics:
                domain = host
        except Exception:
            pass
    if domain:
        keywords = f"{keywords}, {domain}"

    # Build a concise subject line for the image prompt
    subject = clean_title[:120]
    return subject, keywords


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


def _is_usable_size(path: Path, min_width: int = MIN_USABLE_WIDTH, min_height: int = MIN_USABLE_HEIGHT) -> bool:
    """Check downloaded image has usable dimensions for a LinkedIn feed image."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.width >= min_width and im.height >= min_height
    except (OSError, ImportError, ValueError):
        return False


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


def _fetch_page(url: str, timeout: int = 15) -> requests.Response:
    """Fetch a page with a browser-like User-Agent."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "DNT": "1",
        "Connection": "keep-alive",
    }
    return requests.get(url, timeout=timeout, headers=headers)


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


def _download_unsplash(query: str, output_path: Path, width: int = TARGET_WIDTH, height: int = TARGET_HEIGHT) -> Path | None:
    """Download a relevant Unsplash image using the source API (free, no key)."""
    # source.unsplash.com is deprecated/unreliable; try a few query variants before giving up.
    base_queries = [query, query.split()[0] if query else "", "technology abstract"]
    seen = []
    for q in base_queries:
        q = q.strip()
        if not q or q in seen:
            continue
        seen.append(q)
        try:
            encoded = urllib.parse.quote(q)
            url = f"https://source.unsplash.com/{width}x{height}/?{encoded}"
            resp = requests.get(url, timeout=30, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            if not resp.content or len(resp.content) < 4000:
                logger.warning("Unsplash returned empty/too-small response for query: %s", q)
                continue
            _save_response_image(resp, output_path)
            if not _is_usable_size(output_path, min_width=600, min_height=300):
                logger.warning("Unsplash image too small, ignoring %s", output_path)
                output_path.unlink(missing_ok=True)
                continue
            logger.info("Downloaded image from Unsplash (query=%s): %s", q, output_path)
            return output_path
        except (requests.RequestException, OSError, ValueError):
            logger.exception("Unsplash download failed for query: %s", q)
    return None


def _build_unsplash_query(day: str, pillar: str, title: str, linkedin_post: str, hashtags: str) -> str:
    """Create a concise Unsplash search query from post metadata."""
    pillar_lower = (pillar or "").lower()
    title_clean = _clean_for_prompt(title or linkedin_post or "technology")
    # Pull 2-3 meaningful words from title for relevance
    drop_words = {"the", "a", "an", "and", "or", "but", "with", "for", "from", "how", "what", "why", "can", "you", "your", "new", "now", "are", "is", "to", "in", "on", "of", "at", "by"}
    words = [w for w in re.findall(r"[A-Za-z0-9]+", title_clean) if len(w) > 2 and w.lower() not in drop_words]
    keyword_phrase = " ".join(words[:4]) if words else ""

    pillar_map = {
        "security": "cybersecurity technology dark",
        "founder": "business strategy office laptop",
        "tool": "software technology dashboard",
        "builder": "developer coding workspace",
        "tomorrow": "futuristic technology horizon",
        "viral": "technology innovation abstract",
        "pattern": "network technology abstract",
    }
    generic = pillar_map.get(pillar_lower, "technology abstract")
    if keyword_phrase:
        return f"{keyword_phrase} {generic}"
    return generic


def extract_article_images(url: str, item_id: str, max_candidates: int = 4) -> list[str]:
    """Download OG + Twitter + article body image candidates for a URL."""
    candidates_dir = IMAGE_CANDIDATES_DIR / item_id
    candidates_dir.mkdir(parents=True, exist_ok=True)
    found: list[str] = []
    try:
        page_resp = _fetch_page(url, timeout=15)
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
                if path and _is_usable_size(path) and str(path) not in found:
                    found.append(str(path))

        if len(found) < max_candidates:
            tw = soup.find("meta", attrs={"name": "twitter:image"}) or soup.find("meta", property="twitter:image")
            if tw:
                img_url = tw.get("content")
                abs_url = _absolute_url(url, img_url)
                if abs_url:
                    path = _download_image(abs_url, candidates_dir / "twitter.jpg")
                    if path and _is_usable_size(path) and str(path) not in found:
                        found.append(str(path))

        if len(found) < max_candidates:
            selectors = [
                "article img", "main img", ".post-content img", ".entry-content img",
                "figure img", "section img", ".content img", "[itemprop='image']",
                "img[srcset]", "picture img", ".thumbnail img", ".hero img",
            ]
            seen_urls = {Path(p).name.split("?")[0] for p in found}
            for tag in soup.select(", ".join(selectors)):
                if len(found) >= max_candidates:
                    break
                src_attr = tag.get("src") or tag.get("data-src") or tag.get("data-lazy-src") or tag.get("srcset")
                if src_attr and "," in src_attr and "srcset" in tag.attrs:
                    # pick first srcset url
                    src_attr = src_attr.split(",")[0].strip().split(" ")[0]
                abs_url = _absolute_url(url, src_attr)
                if not abs_url:
                    continue
                if not _is_large_enough(tag):
                    continue
                if abs_url.startswith("data:") or abs_url.endswith(".svg"):
                    continue
                url_key = abs_url.split("?")[0]
                if url_key in seen_urls:
                    continue
                suffix = Path(abs_url).suffix or ".jpg"
                suffix = suffix.split("?")[0] or ".jpg"
                if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
                    suffix = ".jpg"
                name = f"article_{len(found)}{suffix}"
                path = _download_image(abs_url, candidates_dir / name)
                if path:
                    seen_urls.add(url_key)
                    if str(path) not in found and _is_usable_size(path):
                        found.append(str(path))
    except requests.HTTPError as exc:
        logger.warning("Article image extraction HTTP error for %s: %s", url, exc)
    except (requests.RequestException, OSError):
        logger.exception("Article image extraction failed for %s", url)
    return found




def _visual_anchor(subject: str, keywords: str, linkedin_post: str) -> str:
    """Pick a concrete visual anchor tied to the post's actual topic.

    Prefer a specific object/scene implied by the title and post text rather
    than a generic icon, so generated images are recognizably relevant.
    """
    text = f"{subject} {keywords} {linkedin_post}".lower()

    # Topic-specific concrete anchors (check longer phrases first)
    anchors = [
        ("decompiler", "decompiled code floating above a circuit board"),
        ("binary", "binary code matrix dissolving into readable source"),
        ("knowledge graph", "a glowing network graph on a dark screen"),
        ("threat intelligence", "a threat-map dashboard with subtle red nodes"),
        ("tokenizer", "a stream of glowing tokens flowing into a neural core"),
        ("token", "a luminous token stream"),
        ("red team", "a red-team operator console with holographic targets"),
        ("vulnerability", "a hardened lock protecting glowing data pathways"),
        ("malware", "isolated malicious code contained inside a glass shield"),
        ("agent", "a constellation of connected AI agent nodes"),
        ("multi-agent", "orbiting agent nodes exchanging glowing messages"),
        ("langgraph", "a branching graph of agent decision nodes"),
        ("orchestration", "a conductor's holographic workflow diagram"),
        ("gpu", "a sleek GPU with luminous data traces"),
        ("inference", "a server rack with pulsing inference pipelines"),
        ("benchmark", "a rising performance chart projected in 3D space"),
        ("reasoning", "a luminous chain-of-thought diagram"),
        ("embedding", "a spiral of semantic vectors"),
        ("memory", "a crystalline memory module"),
        ("attention", "a luminous attention grid"),
        ("transformer", "a transformer architecture block glowing softly"),
        ("fine-tun", "a model being sculpted by precise light beams"),
        ("dataset", "a crystalline data archive"),
        ("founder", "a founder sketching strategy on a whiteboard"),
        ("strategy", "a strategic map with one central chess piece"),
        ("future", "a clean dawn horizon with a single glowing symbol"),
    ]
    for term, anchor in anchors:
        if term in text:
            return anchor

    # Fallback: derive a noun phrase from the first unique keywords
    words = [w.strip() for w in keywords.split(",") if w.strip()]
    if words:
        return f"a polished visualization of {words[0]}"
    return "a clean geometric symbol"


def _build_visual_scene(angle: str, subject: str, keywords: str, pillar: str, source_url: str, linkedin_post: str = "") -> str:
    """Build a concrete, topic-aware scene description for an image angle."""
    angle = (angle or "").strip().lower()
    anchor = _visual_anchor(subject, keywords, linkedin_post)
    topic_word = keywords.split(",")[0].strip() if keywords else "technology"

    if angle == "environment":
        return (
            f"Wide establishing shot of a real-world setting for {subject}: "
            "a calm modern developer workspace, a clean server room with subtle accent lighting, "
            f"or a minimalist lab. {anchor.capitalize()} sits naturally in the scene as a physical prop. "
            "Soft natural light, shallow depth of field, photorealistic, no cartoon illustration, no text."
        )
    if angle == "message":
        return (
            f"Conceptual editorial still-life that communicates the core message of {subject}. "
            f"Center one strong symbolic object: {anchor} on generous negative space, "
            "magazine-cover photographic style, minimal clutter, photorealistic textures, no text."
        )
    if angle == "focus":
        return (
            f"Macro product-photography detail: {anchor} in razor-sharp focus, "
            "creamy bokeh background, professional studio lighting, no people, no text."
        )
    if angle == "pov":
        return (
            f"First-person point-of-view: over-the-shoulder of a builder working on {topic_word}, "
            f"with {anchor} visible on the screen or desk. Immersive and human, shallow depth of field, "
            "professional business context, photorealistic, no text."
        )
    return f"Professional editorial hero shot of {subject}, centered composition, clean background, photorealistic, no text."


def _build_style(pillar: str, keywords: str, stock_style: bool) -> str:
    """Build a topic-aware style string, avoiding generic cityscapes."""
    k = keywords.lower()
    p = (pillar or "").lower()
    parts = []
    if stock_style:
        parts.append(
            "authentic photorealistic stock photograph, clean professional business look, "
            "subtle depth of field, natural color grading, no stylized illustration, no text or labels, "
            "1.91:1 landscape"
        )
        return ", ".join(parts)

    # Topic-driven mood
    if "security" in p or "red team" in k or "vulnerability" in k:
        parts.append(
            "dark cybersecurity editorial scene, subtle lock-shield geometry, amber-red glow on deep blue, "
            "moody cinematic, sharp detail"
        )
    elif "agent" in k or "multi-agent" in k or "orchestration" in k:
        parts.append(
            "photorealistic 3D render of connected nodes, soft blue-purple glow, "
            "minimal dark background, technical editorial, sharp detail, no text"
        )
    elif "llm" in k or "model" in k or "transformer" in k or "attention" in k:
        parts.append(
            "photorealistic 3D render of layered neural geometry, soft cyan and violet light, "
            "futuristic but clean, high detail, no text"
        )
    elif "code" in k or "developer" in k or "builder" in k or "deploy" in k:
        parts.append(
            "photorealistic developer workspace, focused screen glow, warm practical lighting, "
            "authentic textures, no readable text or UI labels"
        )
    elif "founder" in k or "startup" in k or "strategy" in k:
        parts.append(
            "photorealistic strategic office scene, whiteboard or market chart, soft natural window light, "
            "back-or-side view silhouette, no readable text or labels"
        )
    elif "future" in k or "prediction" in k or "horizon" in k:
        parts.append(
            "photorealistic wide futuristic horizon, dawn cityscape silhouette, glowing data streams, "
            "one central symbol, cinematic optimistic mood, no text"
        )
    else:
        parts.append(
            "photorealistic modern tech editorial, clean composition, professional LinkedIn cover style, no text"
        )

    parts.append("1.91:1 landscape, high detail, sharp focus, cinematic lighting")
    return ", ".join(parts)

def prompt_for_post(
    day: str,
    pillar: str,
    title: str,
    linkedin_post: str,
    hashtags: str,
    angle: str = "",
    stock_style: bool = False,
    source_url: str = "",
) -> str:
    """Build a LinkedIn-optimized, topic-aware image prompt from post metadata.

    The optional `angle` lets us generate multiple AI variants from different
    perspectives / environments / messages / POVs while keeping the same core
    subject. `stock_style` requests a photorealistic stock-photo look for
    non-AI fallback slots.
    """
    subject, keywords = _extract_visual_keywords(title, linkedin_post, hashtags, source_url)
    scene = _build_visual_scene(angle, subject, keywords, pillar, source_url, linkedin_post)
    style = _build_style(pillar, keywords, stock_style)

    prompt = (
        f"Professional LinkedIn cover image (1.91:1 landscape) about {subject}. "
        f"Core topic: {keywords}. "
        f"Scene direction: {scene} "
        f"Visual style: {style}. "
        "High detail, sharp focus, cinematic lighting, clean centered composition, "
        "visually striking, suitable for a professional business and developer audience. "
        "No text, letters, numbers, words, logos, watermarks, trademarks, UI chrome, or readable labels. "
        "No people unless explicitly requested by the scene direction."
    )
    return prompt


def _fetch_og_image(url: str, output_path: Path) -> Path | None:
    """Try to download the source article's OpenGraph image."""
    try:
        page_resp = _fetch_page(url, timeout=15)
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


def _generate_with_pollinations(
    prompt: str,
    output_path: Path,
    width: int = TARGET_WIDTH,
    height: int = TARGET_HEIGHT,
    seed: int | None = None,
    model: str = "flux",
) -> Path | None:
    """Generate an image via Pollinations.ai (free, no API key).

    Uses Flux Schnell by default for editorial images; `flux-realism` for
    photorealistic stock-style fallbacks. A stable seed keeps results reproducible.
    """
    encoded = urllib.parse.quote(prompt)
    seed_param = f"&seed={seed}" if seed is not None else ""
    # flux = fast editorial, flux-realism = photorealistic stock photos.
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width={width}&height={height}"
        f"&nologo=true"
        f"&model={model}"
        f"{seed_param}"
        f"&negative_prompt=text,words,letters,numbers,logo,watermark,trademark,UI,labels,signature,lowres,blurry,ugly,deformed,oversaturated"
    )
    # Retry with exponential backoff on rate-limit or transient errors.
    for attempt in range(4):
        try:
            resp = requests.get(url, timeout=180)
            if resp.status_code == 429:
                wait = 5 * (2 ** attempt)
                logger.warning("Pollinations rate-limited (429), retrying in %ss", wait)
                import time
                time.sleep(wait)
                continue
            resp.raise_for_status()
            if not resp.content or len(resp.content) < 4000:
                logger.warning("Pollinations returned empty/too-small response")
                return None
            _save_response_image(resp, output_path)
            if not _is_usable_size(output_path):
                logger.warning("Pollinations image failed size check: %s", output_path)
                output_path.unlink(missing_ok=True)
                return None
            logger.info("Downloaded image from Pollinations.ai: %s", output_path)
            return output_path
        except requests.HTTPError as exc:
            if attempt < 3:
                logger.warning("Pollinations attempt %s failed: %s", attempt + 1, exc)
                import time
                time.sleep(2 * (2 ** attempt))
                continue
            logger.exception("Pollinations.ai generation failed after retries")
            return None
        except (requests.RequestException, OSError, ValueError):
            logger.exception("Pollinations.ai generation failed")
            return None
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


def _generate_image(
    prompt: str,
    output_path: Path,
    provider: str,
    width: int = TARGET_WIDTH,
    height: int = TARGET_HEIGHT,
    seed: int | None = None,
    model: str = "flux",
) -> Path | None:
    """Dispatch to the configured image generation provider."""
    if provider == "fal":
        return _generate_with_fal(prompt, output_path)
    if provider == "pollinations":
        return _generate_with_pollinations(prompt, output_path, width=width, height=height, seed=seed, model=model)
    logger.warning("Unknown image provider %s", provider)
    return None


def _generate_ai_stock_photo(
    day: str,
    pillar: str,
    title: str,
    linkedin_post: str,
    hashtags: str,
    output_path: Path,
    provider: str,
    seed: int,
    source_url: str = "",
) -> Path | None:
    """Generate a photorealistic stock-style image when real stock APIs fail."""
    prompt = prompt_for_post(day, pillar, title, linkedin_post, hashtags, stock_style=True, source_url=source_url)
    logger.info("AI stock photo prompt: %s", prompt)
    return _generate_image(prompt, output_path, provider, seed=seed, model="flux-realism")


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


def candidates_for_post(
    item_url: str,
    title: str,
    day: str,
    pillar: str,
    linkedin_post: str,
    hashtags: str,
    item_id: str | None = None,
    provider: str | None = None,
) -> tuple[Path | None, list[str], str]:
    """Generate a full candidate set for a post.

    Returns:
        (active_image_path, candidate_paths, source_label)

    Policy:
      - Up to 2 non-AI candidates: OG/Twitter/article images first, then Unsplash fallback.
      - Up to 2 AI-generated candidates from different angles: environment, message, focus, pov.
      - The active image is the first usable non-AI candidate if available, otherwise the first
        successful AI-generated candidate.
    """
    if not item_url:
        return None, [], "none"

    chosen_provider = provider or IMAGE_PROVIDER
    candidates_dir = IMAGE_CANDIDATES_DIR / (item_id or _slug(title) or "draft")
    candidates_dir.mkdir(parents=True, exist_ok=True)
    # Stable seed derived from title+item_id so re-runs are deterministic but per-item unique.
    base_seed = abs(hash(f"{title or item_url or ''}:{item_id or ''}:{chosen_provider}")) % (2**31)

    non_ai: list[Path] = []
    ai: list[Path] = []

    # 1. Non-AI: article/OG/Twitter images
    article_cands = extract_article_images(item_url, item_id or _slug(title), max_candidates=NON_AI_CANDIDATES)
    for p in article_cands:
        path = Path(p)
        if path.exists() and _is_usable_size(path) and path not in non_ai:
            non_ai.append(path)
        if len(non_ai) >= NON_AI_CANDIDATES:
            break

    # 2. Non-AI fallback: Pexels (API key) > AI photorealistic stock.
    # Unsplash Source is deprecated and currently returns 503, so we skip it unless Pexels is unavailable.
    if len(non_ai) < NON_AI_CANDIDATES:
        stock_query = _extract_pexels_query(day, pillar, title)
        for i in range(NON_AI_CANDIDATES - len(non_ai)):
            slot_seed = base_seed + i
            out = candidates_dir / f"pexels_{i}.jpg"
            result = _search_pexels(stock_query + (f" {i}" if i else ""), out)
            if result and _is_usable_size(result) and result not in non_ai:
                non_ai.append(result)
                continue
            # Last-resort: AI-generated photorealistic stock photo so we still deliver 4 candidates
            out3 = candidates_dir / f"ai_stock_{i}.png"
            result3 = _generate_ai_stock_photo(
                day, pillar, title, linkedin_post, hashtags, out3, chosen_provider, seed=slot_seed, source_url=item_url
            )
            if result3 and _is_usable_size(result3) and result3 not in non_ai:
                non_ai.append(result3)
            if len(non_ai) >= NON_AI_CANDIDATES:
                break

    # 3. AI candidates: choose exactly 2 angles deterministically from the 4 available
    all_angles = ["environment", "message", "focus", "pov"]
    # Deterministic pair based on item_id so different drafts get different pairs, reruns are stable
    pair_offset = (base_seed + hash(str(item_id or title))) % 4
    angle_pairs = [
        ["environment", "message"],
        ["focus", "pov"],
        ["environment", "focus"],
        ["message", "pov"],
    ]
    chosen_angles = angle_pairs[pair_offset]
    for idx, angle in enumerate(chosen_angles):
        if len(ai) >= AI_CANDIDATES:
            break
        prompt = prompt_for_post(day, pillar, title, linkedin_post, hashtags, angle=angle, source_url=item_url)
        logger.info("AI image prompt (%s): %s", angle, prompt)
        out = candidates_dir / f"ai_{angle}.png"
        seed = base_seed + idx + 100
        result = _generate_image(prompt, out, chosen_provider, seed=seed, model="flux-realism")
        if result and _is_usable_size(result) and result not in ai:
            ai.append(result)

    # Combine candidates with active selection
    all_candidates = [str(p) for p in non_ai + ai]
    if len(all_candidates) < 4:
        logger.warning(
            "Only %s/%s candidates generated for %s (non_ai=%s ai=%s)",
            len(all_candidates), NON_AI_CANDIDATES + AI_CANDIDATES,
            item_id or title, len(non_ai), len(ai)
        )
    active = non_ai[0] if non_ai else (ai[0] if ai else None)
    source = "article" if non_ai else (chosen_provider if ai else "none")
    return active, all_candidates, source


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
    force: bool = False,
) -> tuple[Path | None, str]:
    """Return a local image path for the post, using the cheapest available source.

    This is the legacy single-image entry point. It now delegates to the richer
    candidates_for_post logic and returns the active candidate + source label.
    """
    if not item_url:
        return None, "none"

    chosen_provider = provider or IMAGE_PROVIDER
    h = _slug(title) or _slug(item_url)
    cache_path = IMAGE_DIR / f"{h}.png"

    # Fast-path cache unless forced or skipping OG
    if cache_path.exists() and not skip_og and not force:
        if _is_usable_size(cache_path):
            return cache_path, "cache"
        logger.warning("Cached image too small, ignoring: %s", cache_path)

    active, candidates, source = candidates_for_post(
        item_url=item_url,
        title=title,
        day=day,
        pillar=pillar,
        linkedin_post=linkedin_post,
        hashtags=hashtags,
        item_id=item_id,
        provider=provider,
    )

    # If OG should be skipped, prefer the first AI candidate
    if skip_og and candidates:
        for c in candidates:
            cand_path = Path(c)
            if (chosen_provider in cand_path.name or any(a in cand_path.name for a in ("environment", "message", "focus", "pov"))) and _is_usable_size(cand_path):
                active = cand_path
                source = chosen_provider
                break

    if active:
        return active, source
    return None, "none"


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
