"""Image generation for LinkedIn posts.

Candidate policy:
- Up to 2 non-AI candidates: article OpenGraph/Twitter/body images, plus Unsplash fallback.
- Up to 2 AI-generated candidates from different angles (environment, message, focus, POV).
- Dashboard lets the operator preview all 4 and select the active image for posting.
"""
import datetime
import html
import logging
import os
import re
import urllib.parse
from io import BytesIO
from pathlib import Path
from typing import Any

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
FAL_MODEL = os.getenv("FAL_MODEL", "fal-ai/ideogram/v3")

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
    """Extract the concrete named entity / product / model / company from the title."""
    if not title:
        return ""
    # Preserve hyphenated model names and version numbers: Gemini 3.7, GPT-4o, Llama-3.1
    t = re.sub(r"[^\w\s\-.]", " ", title)
    # Tokenize keeping hyphenated words and versioned numbers
    tokens = re.findall(
        r"[A-Z]{2,}(?=[A-Z][a-z]|\b)|[A-Z][a-z]+|[a-z]+|\d+\.?\d*|\w+(?:-\w+)+",
        t,
    )
    stop_words = {
        "the", "a", "an", "and", "or", "but", "with", "for", "from", "how", "what", "why",
        "can", "you", "your", "new", "now", "are", "is", "to", "in", "on", "of", "at", "by",
        "this", "that", "these", "those", "about", "into", "over", "under", "after", "before",
        "during", "while", "than", "then", "when", "where", "which", "who", "whom", "whose",
        "will", "would", "could", "should", "may", "might", "must", "shall", "need", "dare",
        "ought", "used", "better", "worse", "more", "most", "some", "many", "much", "such",
        "all", "any", "both", "each", "every", "few", "less", "little", "other", "another",
        "one", "two", "three", "first", "last", "next", "previous", "here", "there", "everywhere",
        "nowhere", "somewhere", "everyone", "someone", "anyone", "no", "nothing", "everything",
        "something", "it", "its", "they", "them", "their", "we", "us", "our", "my", "his", "her",
        "him", "she", "he", "i", "me", "already", "hit", "preview", "previews", "teaching",
        "internet", "announced", "released", "launched", "introduces", "shows", "tests", "govern",
        "explained", "analysis", "tutorial", "guide", "breakdown", "opinion", "take", "think",
        "believe", "build", "create", "step", "step-by-step", "deep", "dive", "matters",
    }

    phrases = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok.lower() in stop_words or len(tok) <= 1:
            i += 1
            continue
        # Start a phrase if token is capitalized, contains a digit/version, or is hyphenated
        if tok[0].isupper() or re.search(r"\d", tok) or "-" in tok:
            end = i + 1
            while end < n and (
                tokens[end][0].isupper()
                or re.search(r"\d", tokens[end])
                or tokens[end].lower() in {"of", "for", "with", "and", "v", "vs", "x", "pro", "max", "mini"}
            ):
                end += 1
            phrase = " ".join(tokens[i:end])
            if len(phrase) > 2:
                phrases.append(phrase)
            i = end
        else:
            i += 1

    if not phrases:
        return _extract_fallback_subject(title)

    # Prefer phrase with version number, then most capitalized, then longest
    return max(
        phrases,
        key=lambda s: (
            re.search(r"\d", s) is not None,
            sum(1 for c in s if c.isupper()),
            len(s.split()),
            len(s),
        ),
    )


def _extract_fallback_subject(title: str) -> str:
    """Fallback noun-phrase extractor when no named entity is found."""
    if not title:
        return ""
    stop_words = {
        "the", "a", "an", "and", "or", "but", "with", "for", "from", "how", "what", "why",
        "can", "you", "your", "new", "now", "are", "is", "to", "in", "on", "of", "at", "by",
        "this", "that", "these", "those", "about", "into", "over", "under", "after", "before",
        "during", "while", "than", "then", "when", "where", "which", "who", "whom", "whose",
        "will", "would", "could", "should", "may", "might", "must", "shall", "need",
        "already", "hit", "preview", "previews", "teaching", "internet", "announced",
        "released", "launched", "introduces", "shows", "tests", "govern",
    }
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
    return max(phrases, key=lambda s: (len(s.split()), len(s)))


def _visual_brief(
    title: str,
    linkedin_post: str,
    hashtags: str,
    source_url: str = "",
    pillar: str = "",
) -> dict:
    """Convert post metadata into a structured visual brief.

    Returns a dict with keys: subject, entity, visual_subject, category, event,
    action, composition, context, mood, pillar.
    """
    clean_title = _clean_for_prompt(title, max_len=160)
    clean_post = _clean_for_prompt(linkedin_post, max_len=500)
    clean_hashtags = _clean_for_prompt(hashtags or "", max_len=120)
    text = f"{clean_title} {clean_post} {clean_hashtags}"
    text_lower = text.lower()

    # Entity: named product / model / company / tool from the title.
    entity = _extract_subject(title) or clean_title[:80]
    visual_subject = entity

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

    # Action / state
    action_templates = {
        "launch": "being unveiled or used in a real workspace",
        "explainer": "shown as the central subject so the idea is instantly readable",
        "analysis": "shown in context with supporting visual cues that imply depth",
        "opinion": "presented as a strong editorial focal object",
        "tutorial": "being used hands-on in an authentic workspace",
    }
    action = action_templates.get(event, "shown as the clear focal subject")

    # LinkedIn-first composition
    composition = "one dominant subject off-center, generous negative space, readable thumbnail silhouette"
    if category == "product":
        composition = "product as the single dominant subject, three-quarter angle, clean background, strong silhouette"
    elif category == "security":
        composition = "security hardware or workstation as focal subject, controlled side-light, readable silhouette"
    elif category == "code":
        composition = "developer workstation with one clear focal screen or device, shallow depth of field"
    elif category == "research":
        composition = "research desk with one dominant chart, device, or sample"
    elif event == "launch":
        composition = "product or announcement as the hero subject, minimal stage, balanced negative space"

    # Context
    context = f"a professional technology setting relevant to {entity}"
    if category == "security":
        context = f"a credible security operations or network environment relevant to {entity}"
    elif category == "code":
        context = f"an authentic developer workspace where {entity} is being built or used"
    elif category == "research":
        context = f"a clean research or analysis environment related to {entity}"
    elif category == "product":
        context = f"a modern product or launch context for {entity}"
    elif category == "founder":
        context = f"a strategic founder or leadership setting for {entity}"

    # Mood / editorial style from pillar + category
    pillar_lower = (pillar or "").lower()
    mood_map = {
        "viral_explained": "bold editorial news photography, bright subject separation, strong contrast, immediate recognition",
        "tool_drop": "clean product-forward photography, crisp detail, useful atmosphere",
        "builder_memo": "authentic documentary photography, natural practical lighting, credible engineering environment",
        "pattern_spotting": "analytical editorial photography, connected visual cues, big-picture clarity",
        "tomorrow_in_ai": "optimistic forward-looking editorial photography, thoughtful atmosphere",
        "security_signal": "cybersecurity documentary photography, controlled high-contrast lighting, realistic environment, no cliché neon",
        "founder_signal": "strategic ambitious founder-led editorial photography",
    }
    mood = mood_map.get(pillar_lower, "professional clear editorial photography")
    # Category can refine mood (only when it reinforces clarity)
    if category == "security":
        mood = "cybersecurity documentary photography, controlled high-contrast lighting, realistic environment, no cliché neon"
    elif category == "research":
        mood = "clean research documentary photography, precise composition, professional scientific atmosphere"
    elif category == "code":
        mood = "authentic developer documentary photography, natural practical lighting, real hardware"

    return {
        "subject": clean_title[:120],
        "entity": entity,
        "visual_subject": visual_subject,
        "category": category,
        "event": event,
        "action": action,
        "composition": composition,
        "context": context,
        "mood": mood,
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
        except (ValueError, AttributeError) as exc:
            logger.debug("Domain parsing failed for %s: %s", source_url, exc)
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
    except Exception as exc:  # noqa: BLE001
        logger.debug("dHash failed for %s: %s", path, exc)
        return None

def _visual_anchor(brief: dict, linkedin_post: str = "", angle: str = "") -> str:
    """Pick a concrete, story-driven visual anchor from the brief.

    The anchor describes one clear, photographable moment so the image tells a
    story even without text. Angles are: environment (scene), focus (detail),
    message (symbol), pov (builder view).
    """
    angle = (angle or "environment").lower()
    entity = brief.get("entity") or brief.get("visual_subject") or brief.get("subject") or "technology"
    category = brief.get("category", "technology")
    event = brief.get("event", "concept")

    # Concrete subject by category, avoiding generic words like "AI" or "tool".
    generic = {"technology", "ai", "artificial intelligence", "tool", "app", "platform", "internet", "software", "hardware", "innovation"}
    if entity.lower() in generic or len(entity) < 4:
        visual_subject = {
            "security": "a security analyst workstation with monitors and network hardware",
            "research": "a research analysis desk with charts, instruments, and a laptop",
            "model": "a machine learning workstation with GPU hardware and model graphs",
            "product": "a modern software product shown on a laptop or phone screen",
            "founder": "a strategic founder workspace with notebook and laptop",
            "agent": "an agent orchestration dashboard on a wide monitor",
            "code": "a developer workstation with code on screen and a keyboard",
        }.get(category, "a modern technology workspace with a laptop and clean desk")
    else:
        visual_subject = f"{entity}"

    # Story moment by event + angle
    moments = {
        "environment": {
            "launch": f"a real workspace where {visual_subject} is being unveiled and used by a professional",
            "explainer": f"a clean workspace scene that makes {visual_subject} the obvious subject",
            "analysis": f"a professional setting where {visual_subject} is being studied alongside notes and charts",
            "opinion": f"an editorial scene where {visual_subject} sits as the strong focal object",
            "tutorial": f"a builder\'s hands-on workspace using {visual_subject} step by step",
        },
        "focus": {
            "launch": f"a premium close-up of the core screen, chip, or interface behind {visual_subject} at the moment of use",
            "explainer": f"a crisp detail shot of the single most important object or screen that represents {visual_subject}",
            "analysis": f"a razor-sharp focal detail of {visual_subject} surrounded by subtle analytical cues",
            "opinion": f"a bold macro detail of {visual_subject} isolated on clean negative space",
            "tutorial": f"a tight close-up of {visual_subject} being used by a developer\'s hands",
        },
        "message": {
            "launch": f"one strong symbolic object representing {visual_subject} placed on generous negative space",
            "explainer": f"a single clean object or icon that instantly reads as {visual_subject}",
            "analysis": f"one symbolic artifact for {visual_subject} surrounded by subtle connecting visual cues",
            "opinion": f"a strong standalone symbol for {visual_subject}, editorial still-life",
            "tutorial": f"the essential tool for {visual_subject} shown alone as a clean hero object",
        },
        "pov": {
            "launch": f"an over-the-shoulder first-person view of a builder introducing {visual_subject} to a teammate",
            "explainer": f"a first-person view of someone pointing at {visual_subject} on a screen",
            "analysis": f"a builder\'s POV looking at {visual_subject} with notes and data nearby",
            "opinion": f"a first-person perspective holding the one key object that represents {visual_subject}",
            "tutorial": f"a developer\'s first-person view typing and using {visual_subject}",
        },
    }
    return moments.get(angle, moments["environment"]).get(event, moments["environment"]["explainer"])



def _build_visual_scene(
    angle: str,
    brief: dict,
    source_url: str = "",
    linkedin_post: str = "",
) -> str:
    """Build a concrete, topic-aware, story-driven scene description."""
    angle = (angle or "environment").strip().lower()
    anchor = _visual_anchor(brief, linkedin_post, angle)
    entity = brief.get("entity") or brief.get("visual_subject") or "technology"
    action = brief.get("action", "shown as the clear focal subject")
    composition = brief.get("composition", "one dominant subject, readable thumbnail silhouette")
    context = brief.get("context", f"a professional technology setting relevant to {entity}")

    # Story-first templates, always text-free.
    templates = {
        "environment": (
            f"Wide editorial establishing shot telling a story: {anchor}. "
            f"{context}, {action}. {composition}. "
            "No text, no logos, no words, no letters, no numbers, no UI labels, no watermarks."
        ),
        "message": (
            f"Editorial still-life with a single symbolic story: {anchor}. "
            f"{action}. {composition}. Clean magazine lighting. "
            "No text, no logos, no words, no letters, no numbers, no UI labels, no watermarks."
        ),
        "focus": (
            f"Premium detail shot that tells the story through material: {anchor}. "
            f"Razor-sharp focal point, creamy bokeh. {composition}. "
            "No text, no logos, no words, no letters, no numbers, no UI labels, no watermarks."
        ),
        "pov": (
            f"First-person over-the-shoulder view of the human story: {anchor}. "
            f"{context}, {action}. Shallow depth of field, human scale. "
            "No text, no logos, no words, no letters, no numbers, no UI labels, no watermarks."
        ),
    }
    return templates.get(
        angle,
        f"Professional editorial hero shot of {entity}. {composition}. {context}. "
        "No text, no logos, no words, no letters, no numbers, no UI labels, no watermarks.",
    )


def _build_style(pillar: str, brief: dict | None = None, stock_style: bool = False) -> str:
    """Build a concise topic-aware style string."""
    if stock_style:
        return (
            "authentic photorealistic stock photograph, clean professional business look, "
            "subtle depth of field, natural color grading, no stylized illustration, "
            "no text, no logos, no words, no letters, no numbers, no UI labels, no watermarks, "
            "1.91:1 LinkedIn landscape"
        )
    mood = brief.get("mood", "professional clear editorial photography") if brief else "professional clear editorial photography"
    return (
        f"{mood}, photorealistic, 1.91:1 LinkedIn landscape, "
        "no text, no logos, no words, no letters, no numbers, no UI labels, no watermarks"
    )



def prompt_for_post(
    day: str,
    pillar: str,
    title: str,
    linkedin_post: str,
    hashtags: str,
    angle: str = "",
    source_url: str = "",
    stock_style: bool = False,
) -> str:
    """Create a concise, topic-aware image prompt for a LinkedIn post."""
    brief = _visual_brief(title, linkedin_post, hashtags, source_url, pillar)
    if stock_style:
        scene = _build_visual_scene("environment", brief, source_url, linkedin_post)
        style = _build_style(pillar, brief, stock_style=True)
        return f"{scene}. {style}."
    angle = (angle or "environment").strip().lower()
    scene = _build_visual_scene(angle, brief, source_url, linkedin_post)
    style = _build_style(pillar, brief)
    return f"{scene}. {style}."


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

        # Default Fal model changed to ideogram/v3 for clean, text-free editorial visuals.
        args: dict[str, Any] = {"prompt": prompt}
        if "ideogram" in FAL_MODEL:
            args["aspect_ratio"] = "16:9"
            args["magic_prompt_option"] = "auto"
        else:
            args["image_size"] = "landscape_16_9"
            args["num_inference_steps"] = 4

        handler = fal_client.submit(FAL_MODEL, arguments=args)
        result = handler.get()
        images = result.get("images", [])
        if not images:
            logger.warning("Fal AI returned no images")
            return None
        img_url = images[0].get("url")
        if not img_url:
            logger.warning("Fal AI image URL missing")
            return None
        resp = requests.get(img_url, timeout=(10, 60))
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


PEXELS_LOG_PREFIX = "PEXELS"


def _pexels_cache_key(query: str, index: int) -> Path:
    """Stable cache path for a Pexels search result image."""
    safe = re.sub(r"[^a-z0-9]+", "_", query.lower().strip())[:80]
    return PEXELS_CACHE_DIR / f"{safe}_{index}.jpg"


def _pexels_metadata_path(query: str, index: int) -> Path:
    """Stable cache path for Pexels result metadata."""
    safe = re.sub(r"[^a-z0-9]+", "_", query.lower().strip())[:80]
    return PEXELS_CACHE_DIR / f"{safe}_{index}.json"


def _normalize_pexels_query(query: str) -> str:
    """Normalize query for deduplication."""
    return " ".join(sorted(query.lower().strip().split()))


def _load_pexels_cache(query: str, index: int, output_path: Path) -> Path | None:
    """Return cached image if it is decodable and large enough."""
    import json
    import shutil

    cache_path = _pexels_cache_key(query, index)
    meta_path = _pexels_metadata_path(query, index)
    if not cache_path.exists():
        return None
    try:
        if not _is_usable_size(cache_path, min_width=MIN_USABLE_WIDTH, min_height=MIN_USABLE_HEIGHT):
            logger.info("PEXELS_TOO_SMALL query=%s index=%s path=%s", query, index, cache_path)
            return None
        shutil.copy2(cache_path, output_path)
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        logger.info("PEXELS_CACHE_HIT query=%s index=%s url=%s", query, index, meta.get("url", ""))
        return output_path
    except (OSError, json.JSONDecodeError):
        return None


def _save_pexels_cache(query: str, index: int, output_path: Path, meta: dict) -> None:
    """Persist Pexels image and metadata to cache."""
    import json
    import shutil

    cache_path = _pexels_cache_key(query, index)
    meta_path = _pexels_metadata_path(query, index)
    shutil.copy2(output_path, cache_path)
    meta_path.write_text(json.dumps(meta, indent=2))


def _search_pexels_single(query: str, output_path: Path, index: int = 0) -> tuple[Path | None, str]:
    """Search Pexels for one query and return (path, status)."""
    if not PEXELS_API_KEY:
        logger.warning("PEXELS_AUTH_ERROR no_api_key")
        return None, "PEXELS_AUTH_ERROR"

    cached = _load_pexels_cache(query, index, output_path)
    if cached:
        return cached, "PEXELS_CACHE_HIT"

    logger.info("PEXELS_SEARCH_STARTED query=%s index=%s", query, index)
    headers = {"Authorization": PEXELS_API_KEY}
    params = {"query": query, "per_page": 10, "orientation": "landscape"}

    try:
        resp = requests.get("https://api.pexels.com/v1/search", headers=headers, params=params, timeout=20)
    except requests.RequestException as exc:
        logger.warning("PEXELS_DOWNLOAD_ERROR query=%s index=%s error=%s", query, index, exc)
        return None, "PEXELS_DOWNLOAD_ERROR"

    if resp.status_code == 401:
        logger.warning("PEXELS_AUTH_ERROR query=%s", query)
        return None, "PEXELS_AUTH_ERROR"
    if resp.status_code == 429:
        logger.warning("PEXELS_RATE_LIMIT query=%s", query)
        return None, "PEXELS_RATE_LIMIT"
    if not resp.ok:
        logger.warning("PEXELS_DOWNLOAD_ERROR query=%s status=%s", query, resp.status_code)
        return None, "PEXELS_DOWNLOAD_ERROR"

    try:
        data = resp.json()
    except ValueError:
        logger.warning("PEXELS_INVALID_IMAGE query=%s response_not_json", query)
        return None, "PEXELS_INVALID_IMAGE"

    photos = data.get("photos", [])
    if not photos:
        logger.info("PEXELS_NO_RESULTS query=%s", query)
        return None, "PEXELS_NO_RESULTS"

    import json

    # Cache every returned photo so future requests can reuse it.
    for i, photo in enumerate(photos):
        src = photo.get("src", {}).get("large") or photo.get("src", {}).get("medium")
        if not src:
            continue
        try:
            img_resp = requests.get(src, timeout=20)
            img_resp.raise_for_status()
        except requests.RequestException:
            logger.info("PEXELS_DOWNLOAD_ERROR query=%s index=%s photo_download_failed", query, i)
            continue

        cached_path = _pexels_cache_key(query, i)
        _save_response_image(img_resp, cached_path)
        if not _is_usable_size(cached_path, min_width=MIN_USABLE_WIDTH, min_height=MIN_USABLE_HEIGHT):
            logger.info("PEXELS_TOO_SMALL query=%s index=%s", query, i)
            continue

        meta = {
            "query": query,
            "index": i,
            "url": src,
            "photographer": photo.get("photographer", ""),
            "source_url": photo.get("url", ""),
            "dimensions": {"width": photo.get("width", 0), "height": photo.get("height", 0)},
            "status": "ok",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        _save_pexels_cache(query, i, cached_path, meta)

    # Return requested index if valid, otherwise first valid cached result.
    for i in range(index, len(photos)):
        cached = _pexels_cache_key(query, i)
        meta_path = _pexels_metadata_path(query, i)
        if cached.exists() and _is_usable_size(cached, min_width=MIN_USABLE_WIDTH, min_height=MIN_USABLE_HEIGHT):
            import shutil
            shutil.copy2(cached, output_path)
            meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
            logger.info("PEXELS_SEARCH_SUCCESS query=%s index=%s url=%s", query, i, meta.get("url", ""))
            return output_path, "PEXELS_SEARCH_SUCCESS"

    logger.info("PEXELS_NO_VALID_IMAGE query=%s index=%s", query, index)
    return None, "PEXELS_NO_VALID_IMAGE"


def _search_pexels(queries: list[str], output_path: Path, index: int = 0) -> tuple[Path | None, str, str]:
    """Try multiple Pexels queries and return (path, status, query_used)."""
    if not queries:
        return None, "PEXELS_NO_RESULTS", ""
    last_status = "PEXELS_NO_RESULTS"
    for query in queries:
        path, status = _search_pexels_single(query, output_path, index=index)
        if path and status in ("PEXELS_SEARCH_SUCCESS", "PEXELS_CACHE_HIT"):
            return path, status, query
        last_status = status
    return None, last_status, queries[-1]


def _extract_pexels_query(day: str, pillar: str, title: str) -> str:
    """Create a simple search query for Pexels from post metadata."""
    pillar_map = {
        "security_signal": "cybersecurity technology",
        "founder_signal": "business strategy office laptop",
        "tool_drop": "software technology dashboard",
        "builder_memo": "developer coding workspace",
        "tomorrow_in_ai": "future technology horizon",
        "viral_explained": "technology innovation",
        "pattern_spotting": "network technology abstract",
    }
    generic = pillar_map.get((pillar or "").lower(), "technology abstract")

    clean = _clean_for_prompt(title, max_len=80)
    words = [w for w in re.findall(r"[A-Za-z0-9]+", clean) if len(w) > 3 and w.lower() not in {"about", "with", "from", "this", "that", "their", "your", "already", "previews", "preview", "internet"}]
    keyword_phrase = " ".join(words[:3])

    if keyword_phrase:
        return f"{keyword_phrase} {generic}"
    return generic


def _pexels_queries_for_post(day: str, pillar: str, title: str, linkedin_post: str, hashtags: str) -> list[str]:
    """Generate 2-4 short, visual Pexels queries for a post."""
    base = _extract_pexels_query(day, pillar, title)
    queries = [base]

    clean_title = _clean_for_prompt(title, max_len=80)
    drop = {"about", "with", "from", "this", "that", "their", "your", "already", "previews", "preview", "internet", "announced", "released", "launched", "introduces", "shows", "tests", "explained", "analysis", "guide", "tutorial"}
    words = [w for w in re.findall(r"[A-Za-z0-9]+", clean_title) if len(w) > 3 and w.lower() not in drop]
    if len(words) >= 2:
        queries.append(f"{words[0]} technology")
    if len(words) >= 3:
        queries.append(f"{words[1]} {words[2]}")

    pillar_lower = (pillar or "").lower()
    alt_map = {
        "security_signal": ["cybersecurity professional", "data security"],
        "founder_signal": ["business leadership", "startup office"],
        "tool_drop": ["software dashboard", "technology interface"],
        "builder_memo": ["developer workspace", "programmer laptop"],
        "tomorrow_in_ai": ["future technology", "ai innovation"],
        "viral_explained": ["technology innovation", "modern tech"],
        "pattern_spotting": ["network technology", "connected systems"],
    }
    for alt in alt_map.get(pillar_lower, ["technology abstract"]):
        q = alt.strip()
        if q not in queries:
            queries.append(q)
        if len(queries) >= 4:
            break

    seen = set()
    uniq = []
    for q in queries:
        n = _normalize_pexels_query(q)
        if n and n not in seen:
            seen.add(n)
            uniq.append(q.strip())
    return uniq[:4]


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


def _validate_candidate(
    path: Path,
    seen_hashes: set[str] | None = None,
    min_width: int = MIN_USABLE_WIDTH,
    min_height: int = MIN_USABLE_HEIGHT,
) -> bool:
    """Validate a candidate before it enters the dashboard."""
    if not path or not path.exists():
        return False
    try:
        with Image.open(path) as im:
            w, h = im.size
            if w < min_width or h < min_height:
                logger.info("Candidate too small %s: %sx%s", path, w, h)
                return False
            if w / max(h, 1) < 1.0:
                logger.info("Candidate portrait rejected %s: %sx%s", path, w, h)
                return False
    except (OSError, ValueError) as exc:
        logger.info("Candidate not decodable %s: %s", path, exc)
        return False
    if seen_hashes is not None:
        h = _dhash_image(path)
        if h and h in seen_hashes:
            logger.info("Candidate duplicate rejected %s hash=%s", path, h)
            return False
        if h:
            seen_hashes.add(h)
    return True



def candidates_for_post(
    item_url: str,
    title: str,
    day: str,
    pillar: str,
    linkedin_post: str,
    hashtags: str,
    item_id: str | None = None,
    provider: str | None = None,
) -> tuple[Path | None, list[str], str, list[str]]:
    """Generate up to 4 image candidates for a LinkedIn post.

    Returns (active_path, candidate_paths, active_source, candidate_sources).
    Policy: 2 non-AI (article/stock) + 2 AI from distinct angles.
    """
    chosen_provider = (provider or IMAGE_PROVIDER).lower()
    slug = _slug(title) or _slug(item_url)
    base_seed = abs(hash(f"{slug}:{day}:{pillar}")) % 1_000_000_000
    candidates_dir = IMAGE_CANDIDATES_DIR / slug
    candidates_dir.mkdir(parents=True, exist_ok=True)

    seen_hashes: set[str] = set()
    non_ai: list[Path] = []
    non_ai_sources: list[str] = []

    # 1) Article images (OG / Twitter / body) — most authentic
    if item_url:
        try:
            article_paths = extract_article_images(item_url, slug, max_candidates=NON_AI_CANDIDATES)
            for p in article_paths:
                path = Path(p)
                if _validate_candidate(path, seen_hashes) and path not in non_ai:
                    non_ai.append(path)
                    non_ai_sources.append("Article image")
        except Exception:
            logger.exception("Article image extraction failed")

    # 2) Pexels stock photos with multiple short queries
    if len(non_ai) < NON_AI_CANDIDATES and PEXELS_API_KEY:
        pexels_queries = _pexels_queries_for_post(day, pillar, title, linkedin_post, hashtags)
        for idx in range(NON_AI_CANDIDATES - len(non_ai)):
            out = candidates_dir / f"pexels_{idx}.jpg"
            path, status, query_used = _search_pexels(pexels_queries, out, index=idx)
            if path and status in ("PEXELS_SEARCH_SUCCESS", "PEXELS_CACHE_HIT"):
                # Convert cached/downloaded image to PNG for dashboard consistency
                png_path = out.with_suffix(".png")
                try:
                    with Image.open(path) as im:
                        if im.mode in ("RGBA", "P"):
                            im = im.convert("RGB")
                        im.save(png_path, "PNG")
                    path = png_path
                except (OSError, ValueError):
                    pass
                if _validate_candidate(path, seen_hashes) and path not in non_ai:
                    non_ai.append(path)
                    non_ai_sources.append(f"Pexels · {query_used}")
            if status not in ("PEXELS_SEARCH_SUCCESS", "PEXELS_CACHE_HIT"):
                logger.info("Pexels candidate skipped status=%s", status)

    # 3) Unsplash fallback (free, no key)
    if len(non_ai) < NON_AI_CANDIDATES:
        stock_query = _build_unsplash_query(day, pillar, title, linkedin_post, hashtags)
        for idx in range(NON_AI_CANDIDATES - len(non_ai)):
            out = candidates_dir / f"unsplash_{idx}.png"
            result = _download_unsplash(stock_query, out)
            if result and _validate_candidate(result, seen_hashes) and result not in non_ai:
                non_ai.append(result)
                non_ai_sources.append(f"Unsplash · {stock_query}")

    # 4) AI-generated candidates — two distinct visual strategies
    ai: list[Path] = []
    ai_sources: list[str] = []
    brief = _visual_brief(title, linkedin_post, hashtags, item_url, pillar)
    # Primary pair: environment (wide editorial) + focus (product/detail)
    # Fallback pair: message (symbolic) + pov (builder)
    primary_angles = ["environment", "focus"]
    fallback_angles = ["message", "pov"]

    for idx, angle in enumerate(primary_angles):
        if len(ai) >= AI_CANDIDATES:
            break
        prompt = prompt_for_post(day, pillar, title, linkedin_post, hashtags, angle=angle, source_url=item_url)
        logger.info("AI image prompt (%s): %s", angle, prompt)
        out = candidates_dir / f"ai_{angle}.png"
        seed = base_seed + idx
        result = _generate_image(prompt, out, chosen_provider, seed=seed, model="flux-realism")
        if result and _validate_candidate(result, seen_hashes) and result not in ai:
            ai.append(result)
            ai_sources.append(f"AI · {angle}")

    # If primary pair failed, try fallback pair
    for idx, angle in enumerate(fallback_angles):
        if len(ai) >= AI_CANDIDATES:
            break
        prompt = prompt_for_post(day, pillar, title, linkedin_post, hashtags, angle=angle, source_url=item_url)
        out = candidates_dir / f"ai_{angle}_fallback.png"
        seed = base_seed + idx + 100
        result = _generate_image(prompt, out, chosen_provider, seed=seed, model="flux-realism")
        if result and _validate_candidate(result, seen_hashes) and result not in ai:
            ai.append(result)
            ai_sources.append(f"AI · {angle}")

    # If still short, generic AI stock-style fallback (honestly labeled)
    for idx in range(AI_CANDIDATES - len(ai)):
        if len(ai) >= AI_CANDIDATES:
            break
        prompt = prompt_for_post(day, pillar, title, linkedin_post, hashtags, stock_style=True, source_url=item_url)
        logger.info("AI fallback stock prompt: %s", prompt)
        out = candidates_dir / f"ai_fallback_{idx}.png"
        seed = base_seed + idx + 200
        result = _generate_image(prompt, out, chosen_provider, seed=seed, model="flux-realism")
        if result and _validate_candidate(result, seen_hashes) and result not in ai:
            ai.append(result)
            ai_sources.append("AI · stock-style fallback")

    # Combine candidates
    all_paths = non_ai + ai
    all_sources = non_ai_sources + ai_sources
    all_candidates = [str(p) for p in all_paths]

    if len(all_candidates) < 4:
        logger.warning(
            "Only %s/%s candidates generated for %s",
            len(all_candidates), NON_AI_CANDIDATES + AI_CANDIDATES, slug,
        )

    # Rank candidates and pick the best as the active image
    chosen_angles = primary_angles + fallback_angles
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