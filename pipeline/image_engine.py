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

PEXELS_CACHE_DIR = DATA_DIR / "pexels_cache"
PEXELS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

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



def _extract_subject(title: str) -> str:
    """Pull the most concrete noun phrase from a title to use as the visual anchor."""
    if not title:
        return ""
    stop_words = {
        "the", "a", "an", "and", "or", "but", "with", "for", "from", "how", "what", "why",
        "can", "you", "your", "new", "now", "are", "is", "to", "in", "on", "of", "at", "by",
        "this", "that", "these", "those", "about", "into", "over", "under", "after", "before",
        "during", "while", "than", "then", "when", "where", "which", "who", "whom", "whose",
        "will", "would", "could", "should", "may", "might", "must", "shall", "need", "dare",
        "ought", "used", "better", "worse", "more", "most", "some", "many", "much", "such",
        "all", "any", "both", "each", "every", "few", "less", "little", "other", "another",
        "one", "two", "three", "first", "last", "next", "previous", "here", "there", "everywhere",
        "nowhere", "somewhere", "everyone", "someone", "anyone", "no", "one", "nothing", "everything",
        "something", "it", "its", "they", "them", "their", "we", "us", "our", "my", "his", "her",
        "him", "she", "he", "i", "me", "already", "hit", "preview", "previews", "teaching",
        "internet", "announced", "released", "launched", "introduces", "shows", "tests", "govern",
    }
    # Strip possessives and non-alpha, keep hyphens
    t = re.sub(r"['’]s\b", "", title.lower())
    t = re.sub(r"[^a-z0-9\s-]", "", t)
    tokens = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", t)

    def tag(tok):
        if tok in stop_words or len(tok) <= 2:
            return None
        if tok.endswith(("y", "er", "est", "ful", "ous", "ive", "al", "ing", "ed", "less", "able", "ible")):
            return "adj"
        return "noun"

    phrases = []
    i = 0
    n = len(tokens)
    while i < n:
        window = [(tokens[j], tag(tokens[j])) for j in range(i, min(i + 8, n))]
        first_noun = next((j for j, (_, tg) in enumerate(window) if tg == "noun"), None)
        if first_noun is None:
            i += 1
            continue
        start = first_noun
        while start > 0 and window[start - 1][1] == "adj":
            start -= 1
        end = first_noun + 1
        while end < len(window) and window[end][1] == "noun":
            end += 1
        phrase = " ".join(window[k][0] for k in range(start, end))
        if len(phrase) > 3:
            phrases.append(phrase)
        i = end

    if not phrases:
        return ""
    # Prefer longer phrase, then earlier in title
    return max(phrases, key=lambda s: (len(s.split()), len(s)))


def _visual_brief(
    title: str,
    linkedin_post: str,
    hashtags: str,
    source_url: str = "",
    pillar: str = "",
) -> dict:
    """Convert post metadata into a structured visual brief.

    Returns a dict with keys: subject, visual_subject, category, event, tone, pillar.
    """
    clean_title = _clean_for_prompt(title, max_len=160)
    clean_post = _clean_for_prompt(linkedin_post, max_len=500)
    clean_hashtags = _clean_for_prompt(hashtags or "", max_len=120)
    text = f"{clean_title} {clean_post} {clean_hashtags}"
    text_lower = text.lower()

    # Concrete visual subject: prefer the strongest noun phrase from the title.
    visual_subject = (_extract_subject(clean_title) or clean_title[:80]).title()

    # Category detection from content signals
    category = "technology"
    category_signals = {
        "security": ["security", "cyber", "vulnerability", "exploit", "threat", "malware", "red team", "jailbreak", "attack", "cve", "payload"],
        "research": ["research", "paper", "study", "benchmark", "evaluation", "arxiv"],
        "model": ["llm", "language model", "foundation model", "model release", "gpt", "gemini", "claude"],
        "product": ["launch", "release", "product", "tool", "platform", "app", "api", "framework"],
        "founder": ["founder", "startup", "strategy", "ceo", "entrepreneur"],
        "agent": ["agent", "agentic", "multi-agent", "orchestration", "workflow", "delegate"],
        "code": ["coding", "developer", "code", "programming", "github", "repo"],
    }
    for cat, signals in category_signals.items():
        if any(s in text_lower for s in signals):
            category = cat
            break

    # Event detection
    event = "concept"
    event_signals = {
        "launch": ["launch", "release", "drops", "announced", "introducing", "new"],
        "explainer": ["explained", "how", "what is", "primer", "guide", "breakdown"],
        "analysis": ["analysis", "deep dive", "implications", "why it matters"],
        "opinion": ["opinion", "take", "hot take", "think", "believe"],
        "tutorial": ["tutorial", "how to", "build", "create", "step-by-step"],
    }
    for ev, signals in event_signals.items():
        if any(s in text_lower for s in signals):
            event = ev
            break

    # Tone from pillar + event
    pillar_lower = (pillar or "").lower()
    tone_map = {
        "viral_explained": "bold, news-style, curiosity-driven",
        "tool_drop": "clean, product-forward, useful",
        "builder_memo": "practical, hands-on, maker-focused",
        "pattern_spotting": "analytical, connected, big-picture",
        "tomorrow_in_ai": "optimistic, forward-looking, thoughtful",
        "security_signal": "serious, urgent, credible",
        "founder_signal": "strategic, ambitious, founder-led",
    }
    tone = tone_map.get(pillar_lower, "professional, clear")

    return {
        "subject": clean_title[:120],
        "visual_subject": visual_subject,
        "category": category,
        "event": event,
        "tone": tone,
        "pillar": pillar,
    }



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

    # Deduplicate visually identical images (same OG/Twitter card, etc.)
    unique: list[str] = []
    seen_hashes: set[str] = set()
    for p in found:
        h = _dhash_image(Path(p))
        if h is None or h not in seen_hashes:
            if h:
                seen_hashes.add(h)
            unique.append(p)
    return unique






def _dhash_image(path: Path, size: int = 8) -> str | None:
    """Compute a simple perceptual hash (dHash) for an image."""
    try:
        img = Image.open(path).convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
        pixels = list(img.getdata())
        diff = []
        for row in range(size):
            for col in range(size):
                left = pixels[row * (size + 1) + col]
                right = pixels[row * (size + 1) + col + 1]
                diff.append(left > right)
        return hex(int("".join("1" if b else "0" for b in diff), 2))[2:].zfill(size * size // 4)
    except Exception:
        return None

def _visual_anchor(brief: dict, linkedin_post: str = "", angle: str = "") -> str:
    """Pick a concrete, photographable anchor from the visual brief."""
    subject = brief.get("visual_subject") or brief.get("subject") or "technology"
    category = brief.get("category", "technology")
    event = brief.get("event", "concept")
    angle = (angle or brief.get("visual_archetype", "environment")).lower()

    # If subject is generic, fall back to category-specific noun
    generic = {"technology", "ai", "artificial intelligence", "tool", "app", "platform", "internet"}
    if subject.lower() in generic or len(subject) < 4:
        subject = {
            "security": "cybersecurity system",
            "research": "AI research lab",
            "model": "machine learning model",
            "product": "software product",
            "founder": "startup workspace",
            "agent": "AI agent system",
            "code": "developer workspace",
        }.get(category, "modern technology")

    # Angle templates that embed the actual subject.
    templates = {
        "environment": f"a real-world scene where {subject} is being built, tested, or used",
        "message": f"one strong symbolic object that represents {subject} on generous negative space",
        "focus": f"a premium macro detail of the core hardware, interface, or material behind {subject}",
        "pov": f"a first-person over-the-shoulder view of a builder working with {subject}",
    }
    anchor = templates.get(angle, templates["environment"])

    # Category-specific tweaks to avoid abstract clichés
    if category == "security" and angle == "message":
        anchor = f"a polished steel padlock on a glass table with soft red light, representing {subject}"
    elif category == "agent" and angle == "message":
        anchor = f"a constellation of glowing glass spheres linked by thin cables, symbolising {subject}"
    elif category == "model" and angle == "focus":
        anchor = f"macro of a premium GPU edge with cyan data traces reflected on brushed metal, core to {subject}"
    elif category == "product" and angle == "environment":
        anchor = f"a modern product launch stage with soft spotlights and a large screen showing {subject}"
    elif category == "code" and angle == "pov":
        anchor = f"over-the-shoulder of a developer reviewing code and diagrams related to {subject}"

    return anchor



def _build_visual_scene(
    angle: str,
    brief: dict,
    source_url: str = "",
    linkedin_post: str = "",
) -> str:
    """Build a concrete, topic-aware scene description for an image angle."""
    angle = (angle or "environment").strip().lower()
    anchor = _visual_anchor(brief, linkedin_post, angle)
    subject = brief.get("visual_subject") or brief.get("subject") or "technology"
    tone = brief.get("tone", "professional")

    if angle == "environment":
        return f"Wide establishing shot of {anchor}. Natural context for {subject}, soft ambient light, documentary editorial style, no text, no logos."
    if angle == "message":
        return f"Editorial still-life centered on {anchor}. Generous negative space, magazine-cover lighting, communicating the core idea of {subject}. No text, no logos."
    if angle == "focus":
        return f"Premium macro detail: {anchor}. Razor-sharp focal point, creamy bokeh, professional product photography, no text, no logos."
    if angle == "pov":
        return f"First-person over-the-shoulder view: {anchor}. Shallow depth of field, authentic workspace, human scale, no text, no logos."
    return f"Professional editorial hero shot of {subject}, centered composition, clean background, photorealistic, no text, no logos."



def _build_style(pillar: str, brief: dict | None = None, stock_style: bool = False) -> str:
    """Build a concise topic-aware style string."""
    pillar_lower = (pillar or "").lower()
    tone = brief.get("tone", "") if brief else ""
    category = brief.get("category", "") if brief else ""

    if stock_style:
        return (
            "authentic photorealistic stock photograph, clean professional business look, "
            "subtle depth of field, natural color grading, no stylized illustration, no text or labels, "
            "1.91:1 landscape"
        )

    mood = "photorealistic modern tech editorial, clean composition, professional LinkedIn cover style"
    if "viral" in pillar_lower:
        mood = "bold news-style editorial photography, strong focal point, high contrast, scroll-stopping hero image"
    elif "security" in pillar_lower or category == "security":
        mood = "dark cybersecurity documentary scene, subtle red-amber glow on deep blue-grey, cinematic contrast"
    elif "founder" in pillar_lower:
        mood = "warm strategic editorial portrait lighting, natural window light, authentic founder-office textures"
    elif "tool" in pillar_lower or category == "product":
        mood = "clean product-forward editorial, soft studio lighting, premium materials, minimal clutter"
    elif "builder" in pillar_lower or category == "code":
        mood = "authentic developer workspace photography, focused screen glow, warm practical lighting"
    elif category == "agent":
        mood = "photorealistic 3D render of connected glass nodes, soft blue-purple glow, minimal dark background"
    elif category == "model":
        mood = "modern tech editorial, clean composition, subtle cyan-violet light, professional LinkedIn cover style"
    elif category == "research":
        mood = "clean scientific editorial, crisp whites and soft accent lighting, documentary precision"
    elif "tomorrow" in pillar_lower:
        mood = "optimistic wide horizon editorial, warm dawn light, subtle futuristic atmosphere"

    return f"{mood}, 1.91:1 landscape, high detail, sharp focus, cinematic lighting, no text, no logos"



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
    """Build a simple, high-relevance LinkedIn cover-image prompt.

    The optional `angle` lets us generate multiple AI variants from different
    perspectives (environment / message / focus / POV) while keeping the same
    concrete subject.
    """
    brief = _visual_brief(title, linkedin_post, hashtags, source_url, pillar)
    if angle:
        brief["visual_archetype"] = angle

    scene = _build_visual_scene(angle or brief.get("visual_archetype", "environment"), brief, source_url, linkedin_post)
    style = _build_style(pillar, brief, stock_style)

    return (
        f"LinkedIn cover image about {brief['visual_subject']}.\n"
        f"Scene: {scene}\n"
        f"Style: {style}.\n"
        f"Restrictions: no text, letters, numbers, words, logos, watermarks, trademarks, UI chrome, "
        f"captions, or readable labels. No people unless the scene explicitly calls for them."
    )



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
            resp = requests.get(url, timeout=(15, 60))
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
        resp = requests.get(img_url, timeout=(10, 30))
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
    logger.info("AI fallback photo prompt: %s", prompt)
    return _generate_image(prompt, output_path, provider, seed=seed, model="flux-realism")


def _pexels_cache_key(query: str, index: int) -> Path:
    """Stable cache path for a Pexels search result."""
    safe = re.sub(r"[^a-z0-9]+", "_", query.lower()).strip("_")[:80]
    return PEXELS_CACHE_DIR / f"{safe}_{index}.jpg"


def _search_pexels(query: str, output_path: Path, index: int = 0) -> Path | None:
    """Search Pexels for a free stock photo, with local caching.

    Reuses cached results for the same query+index to avoid repeated API calls.
    """
    if not PEXELS_API_KEY:
        return None

    cache_path = _pexels_cache_key(query, index)
    if cache_path.exists():
        try:
            if _is_usable_size(cache_path):
                # Hard-link or copy cached image to requested output path
                import shutil
                shutil.copy2(cache_path, output_path)
                logger.info("Reused cached Pexels image for query=%s index=%s: %s", query, index, output_path)
                return output_path
        except OSError:
            pass

    try:
        headers = {"Authorization": PEXELS_API_KEY}
        params = {"query": query, "per_page": 10, "orientation": "landscape"}
        resp = requests.get("https://api.pexels.com/v1/search", headers=headers, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        photos = data.get("photos", [])
        if not photos:
            return None

        # Cache all returned images for future reuse
        for i, photo in enumerate(photos):
            src = photo.get("src", {}).get("large") or photo.get("src", {}).get("medium")
            if not src:
                continue
            img_resp = requests.get(src, timeout=20)
            img_resp.raise_for_status()
            cached = _pexels_cache_key(query, i)
            _save_response_image(img_resp, cached)

        # Return requested index if available, else first valid
        for i in range(index, len(photos)):
            cached = _pexels_cache_key(query, i)
            if cached.exists() and _is_usable_size(cached):
                import shutil
                shutil.copy2(cached, output_path)
                logger.info("Downloaded image from Pexels (query=%s, index=%s): %s", query, i, output_path)
                return output_path
    except (requests.RequestException, OSError, ValueError, KeyError):
        logger.exception("Pexels search failed")
    return None


def _extract_pexels_query(day: str, pillar: str, title: str) -> str:
    """Create a simple search query for Pexels from post metadata."""
    pillar_map = {
        "security_signal": "cybersecurity technology dark",
        "founder_signal": "business strategy office laptop",
        "tool_drop": "software technology dashboard",
        "builder_memo": "developer coding workspace",
        "tomorrow_in_ai": "futuristic technology horizon",
        "viral_explained": "technology innovation abstract",
        "pattern_spotting": "network technology abstract",
    }
    generic = pillar_map.get((pillar or "").lower(), "technology abstract")

    clean = _clean_for_prompt(title, max_len=80)
    words = [w for w in re.findall(r"[A-Za-z0-9]+", clean) if len(w) > 3 and w.lower() not in {"about", "with", "from", "this", "that", "their", "your", "already", "previews", "preview", "internet"}]
    keyword_phrase = " ".join(words[:3])

    if keyword_phrase:
        return f"{keyword_phrase} {generic}"
    return generic



def _score_candidate(
    path: Path,
    brief: dict,
    source: str,
    angle: str = "",
) -> float:
    """Score a candidate image on relevance, specificity, novelty, composition, and quality.

    Returns a float 0-100. Higher is better.
    """
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
    except (OSError, ValueError):
        return 0.0

    # Quality: resolution and aspect ratio fit
    aspect = w / max(h, 1)
    target_aspect = TARGET_WIDTH / TARGET_HEIGHT
    aspect_penalty = max(0, 15 - abs(aspect - target_aspect) * 30)
    resolution_score = min(25, (w * h) / 100000)

    # Source preference: authentic > stock > AI
    source_scores = {
        "article": 22,
        "og": 22,
        "twitter": 20,
        "stock": 15,
        "pexels": 15,
        "ai": 8,
    }
    source_score = source_scores.get(source.lower().split()[0], 8)

    # Specificity: does the filename hint at a concrete angle?
    lower_name = path.name.lower()
    specificity_score = 10
    if angle:
        specificity_score += 5
    if any(x in lower_name for x in ("og", "article", "pexels")):
        specificity_score += 5

    # Relevance: prefer candidates that match the category
    category = brief.get("category", "technology")
    relevance_score = 15
    category_keywords = {
        "security": ["lock", "shield", "cyber", "threat"],
        "model": ["model", "neural", "gpu", "workstation"],
        "research": ["paper", "chart", "lab"],
        "product": ["product", "device", "phone", "screen"],
        "founder": ["office", "whiteboard", "chess"],
        "agent": ["node", "sphere", "network"],
        "code": ["code", "keyboard", "desk"],
    }
    for kw in category_keywords.get(category, []):
        if kw in lower_name:
            relevance_score += 5
            break

    # Novelty: penalize generic names
    generic = ["abstract", "technology", "generic"]
    if any(g in lower_name for g in generic):
        relevance_score -= 5

    total = resolution_score + aspect_penalty + source_score + specificity_score + relevance_score
    return min(100.0, max(0.0, total))


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
      - Exactly 4 candidates when possible: 2 non-AI (article/stock) + 2 AI.
      - AI candidates use two different angles from [environment, message, focus, pov].
      - The active image is the highest-scoring candidate.
    """
    if not item_url:
        return None, [], "none"

    chosen_provider = provider or IMAGE_PROVIDER
    slug = item_id or _slug(title) or "draft"
    candidates_dir = IMAGE_CANDIDATES_DIR / slug
    candidates_dir.mkdir(parents=True, exist_ok=True)
    base_seed = abs(hash(f"{title or item_url or ''}:{slug}:{chosen_provider}")) % (2**31)

    non_ai: list[Path] = []
    non_ai_sources: list[str] = []

    # 1. Article images (OpenGraph/Twitter/body), deduplicated
    article_cands = extract_article_images(item_url, slug, max_candidates=NON_AI_CANDIDATES)
    for p in article_cands:
        path = Path(p)
        if path.exists() and _is_usable_size(path) and path not in non_ai:
            non_ai.append(path)
            non_ai_sources.append("article")
        if len(non_ai) >= NON_AI_CANDIDATES:
            break

    # 2. Stock fallback (Pexels)
    if len(non_ai) < NON_AI_CANDIDATES and PEXELS_API_KEY:
        stock_query = _extract_pexels_query(day, pillar, title)
        for i in range(NON_AI_CANDIDATES - len(non_ai)):
            out = candidates_dir / f"pexels_{i}.jpg"
            result = _search_pexels(stock_query, out, index=i)
            if result and _is_usable_size(result) and result not in non_ai:
                non_ai.append(result)
                non_ai_sources.append("stock")
            if len(non_ai) >= NON_AI_CANDIDATES:
                break

    # 3. Unsplash fallback if still short
    if len(non_ai) < NON_AI_CANDIDATES:
        stock_query = _build_unsplash_query(day, pillar, title, linkedin_post, hashtags)
        for i in range(NON_AI_CANDIDATES - len(non_ai)):
            out = candidates_dir / f"unsplash_{i}.jpg"
            result = _download_unsplash(stock_query, out)
            if result and _is_usable_size(result) and result not in non_ai:
                non_ai.append(result)
                non_ai_sources.append("stock")
            if len(non_ai) >= NON_AI_CANDIDATES:
                break

    # 4. AI candidates: always attempt 2 distinct angles
    ai: list[Path] = []
    ai_sources: list[str] = []
    all_angles = ["environment", "message", "focus", "pov"]
    pair_offset = base_seed % 4
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
            ai_sources.append(f"AI · {angle}")

    # If AI generation failed, fill remaining slots with generic AI fallbacks
    for idx, angle in enumerate([a for a in all_angles if a not in [x.split()[-1] for x in ai_sources]]):
        if len(ai) >= AI_CANDIDATES:
            break
        prompt = prompt_for_post(day, pillar, title, linkedin_post, hashtags, angle=angle, source_url=item_url)
        out = candidates_dir / f"ai_{angle}_fallback.png"
        seed = base_seed + idx + 200
        result = _generate_image(prompt, out, chosen_provider, seed=seed, model="flux-realism")
        if result and _is_usable_size(result) and result not in ai:
            ai.append(result)
            ai_sources.append(f"AI · {angle}")

    # Combine candidates with active selection
    all_paths = non_ai + ai
    all_sources = non_ai_sources + ai_sources
    all_candidates = [str(p) for p in all_paths]

    if len(all_candidates) < 4:
        logger.warning(
            "Only %s/%s candidates generated for %s",
            len(all_candidates), NON_AI_CANDIDATES + AI_CANDIDATES, slug,
        )

    # Rank candidates and pick the best as the active image
    brief = _visual_brief(title, linkedin_post, hashtags, item_url, pillar)
    scored: list[tuple[float, Path, str]] = []
    for idx, p in enumerate(all_paths):
        source_label = all_sources[idx]
        angle = chosen_angles[idx - len(non_ai)] if idx >= len(non_ai) else ""
        score = _score_candidate(p, brief, source_label, angle)
        scored.append((score, p, source_label))

    scored.sort(key=lambda x: x[0], reverse=True)
    active = scored[0][1] if scored else None
    source = scored[0][2] if scored else "none"

    ranked_paths = [str(p) for _s, p, _l in scored]
    ranked_sources = [l for _s, _p, l in scored]
    remaining = [(c, all_sources[all_candidates.index(c)]) for c in all_candidates if c not in ranked_paths]
    final_paths = ranked_paths + [c for c, _ in remaining]
    final_sources = ranked_sources + [s for _, s in remaining]

    return active, final_paths, source, final_sources



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

    active, candidates, source, _candidate_sources = candidates_for_post(
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