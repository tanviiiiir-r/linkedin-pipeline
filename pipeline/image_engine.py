"""Image generation for LinkedIn posts via RunPod ComfyUI.

Fallback chain:
1. Source article OpenGraph image (free, fast, relevant)
2. RunPod ComfyUI Flux generation (custom, costs GPU credits)
3. Text-only post if both fail

Default workflow is the existing Flux SamplerCustomAdvanced workflow extracted from
pod output metadata, using flux1-dev.sft + t5xxl_fp8 + clip_l + ae.sft.
"""
import json
import logging
import random
import re
import threading
import time
from pathlib import Path

import requests

from config.settings import DATA_DIR
from pipeline.log import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

RUNPOD_API_KEY = __import__("os").getenv("RUNPOD_API_KEY", "")
RUNPOD_POD_ID = __import__("os").getenv("RUNPOD_POD_ID", "")
COMFY_PROXY_URL = __import__("os").getenv("COMFY_PROXY_URL", "")
PAUSE_AFTER_SECONDS = int(__import__("os").getenv("PAUSE_AFTER_SECONDS", "300"))
COMFY_INIT_DELAY_SECONDS = int(__import__("os").getenv("COMFY_INIT_DELAY_SECONDS", "300"))

IMAGE_DIR = DATA_DIR / "images"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_CANDIDATES_DIR = DATA_DIR / "image_candidates"
IMAGE_CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)



def _generate_placeholder(title: str, output_path: Path, width: int = 1200, height: int = 627) -> Path:
    """Create a branded placeholder image when OG and ComfyUI both fail."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.warning("Pillow not installed; cannot generate placeholder image")
        return None
    img = Image.new("RGB", (width, height), color="#0f172a")
    draw = ImageDraw.Draw(img)
    for y in range(height):
        r = int(15 + (y / height) * 25)
        g = int(23 + (y / height) * 30)
        b = int(42 + (y / height) * 45)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    except (OSError, ValueError):
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()
    words = title.split()
    lines = []
    line = ""
    for word in words:
        test = f"{line} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font_large)
        if bbox[2] - bbox[0] < width - 120:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    lines = lines[:3]
    y_offset = height // 2 - (len(lines) * 60) // 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font_large)
        x = (width - (bbox[2] - bbox[0])) // 2
        draw.text((x, y_offset), line, fill="#f8fafc", font=font_large)
        y_offset += 70
    footer = "Secure AI Engineering"
    fbbox = draw.textbbox((0, 0), footer, font=font_small)
    fx = (width - (fbbox[2] - fbbox[0])) // 2
    draw.text((fx, height - 80), footer, fill="#94a3b8", font=font_small)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)
    logger.info("Generated placeholder image: %s", output_path)
    return output_path

# Default Flux workflow extracted from the running pod metadata
DEFAULT_FLUX_WORKFLOW = {
    "6": {
        "inputs": {
            "text": "",
            "clip": ["11", 0]
        },
        "class_type": "CLIPTextEncode",
        "_meta": {"title": "CLIP Text Encode (Positive Prompt)"}
    },
    "8": {
        "inputs": {
            "samples": ["13", 0],
            "vae": ["10", 0]
        },
        "class_type": "VAEDecode",
        "_meta": {"title": "VAE Decode"}
    },
    "9": {
        "inputs": {
            "filename_prefix": "ComfyUI",
            "images": ["8", 0]
        },
        "class_type": "SaveImage",
        "_meta": {"title": "Save Image"}
    },
    "10": {
        "inputs": {"vae_name": "ae.sft"},
        "class_type": "VAELoader",
        "_meta": {"title": "Load VAE"}
    },
    "11": {
        "inputs": {
            "clip_name1": "t5xxl_fp8_e4m3fn.safetensors",
            "clip_name2": "clip_l.safetensors",
            "type": "flux",
            "device": "default"
        },
        "class_type": "DualCLIPLoader",
        "_meta": {"title": "DualCLIPLoader"}
    },
    "12": {
        "inputs": {
            "unet_name": "flux1-dev.sft",
            "weight_dtype": "default"
        },
        "class_type": "UNETLoader",
        "_meta": {"title": "Load Diffusion Model"}
    },
    "13": {
        "inputs": {
            "noise": ["25", 0],
            "guider": ["22", 0],
            "sampler": ["16", 0],
            "sigmas": ["17", 0],
            "latent_image": ["27", 0]
        },
        "class_type": "SamplerCustomAdvanced",
        "_meta": {"title": "SamplerCustomAdvanced"}
    },
    "16": {
        "inputs": {"sampler_name": "euler"},
        "class_type": "KSamplerSelect",
        "_meta": {"title": "KSamplerSelect"}
    },
    "17": {
        "inputs": {
            "scheduler": "simple",
            "steps": 20,
            "denoise": 1.0,
            "model": ["12", 0]
        },
        "class_type": "BasicScheduler",
        "_meta": {"title": "BasicScheduler"}
    },
    "22": {
        "inputs": {
            "model": ["12", 0],
            "conditioning": ["26", 0]
        },
        "class_type": "BasicGuider",
        "_meta": {"title": "BasicGuider"}
    },
    "25": {
        "inputs": {"noise_seed": 0},
        "class_type": "RandomNoise",
        "_meta": {"title": "RandomNoise"}
    },
    "26": {
        "inputs": {
            "guidance": 3.5,
            "conditioning": ["6", 0]
        },
        "class_type": "FluxGuidance",
        "_meta": {"title": "FluxGuidance"}
    },
    "27": {
        "inputs": {
            "width": 1216,
            "height": 704,
            "batch_size": 1
        },
        "class_type": "EmptySD3LatentImage",
        "_meta": {"title": "EmptySD3LatentImage"}
    }
}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60]


def _clean_for_prompt(text: str) -> str:
    """Remove URLs, markdown, overly technical tokens, and keep only visual words."""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[#@]\w+", "", text)
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"\n+", ". ", text)
    text = re.sub(r"\s+", " ", text)
    # Truncate long posts to first 200 chars for prompt
    return text.strip()[:240]


def prompt_for_post(day: str, pillar: str, title: str, linkedin_post: str, hashtags: str) -> str:
    """Build a LinkedIn-optimized image prompt from post metadata."""
    base = _clean_for_prompt(title or linkedin_post)
    day_lower = day.lower()
    pillar_lower = pillar.lower()

    style_fragments = []
    if "tool" in pillar_lower or "monday" in day_lower:
        style_fragments.append("clean abstract SaaS product hero card, dark mode, single icon plus tool-name area, minimal, 1.91:1 landscape")
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

    # Extract brand/entity if present
    entities = re.findall(r"\b(AWS|Google|OpenAI|Anthropic|Meta|Microsoft|NVIDIA|Pinterest|Cloudflare|Amazon|DeepMind|Gemini|Nvidia)\b", base)
    entity_clause = ""
    if entities:
        entity_clause = f" Inspired by {entities[0]} aesthetic but no logos, trademarks, or text."

    prompt = (
        f"Professional LinkedIn post header image about {base}. "
        f"{style}.{entity_clause} "
        "Completely free of text, letters, numbers, logos, watermarks, trademarks, UI chrome, and readable labels. "
        "High quality, 8k, photorealistic or clean vector illustration, centered composition, safe for business audience."
    )
    return prompt


def _runpod_graphql(query: str, variables: dict | None = None) -> dict:
    if not RUNPOD_API_KEY:
        raise RuntimeError("RUNPOD_API_KEY not set")
    resp = requests.post(
        "https://api.runpod.io/graphql",
        headers={"Authorization": f"Bearer {RUNPOD_API_KEY}"},
        json={"query": query, "variables": variables or {}},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    # Surface GraphQL-level errors for mutations so callers can act.
    if "errors" in data and not data.get("data"):
        messages = ", ".join(e.get("message", "") for e in data["errors"])
        raise RuntimeError(f"RunPod GraphQL error: {messages}")
    return data


def pod_status() -> str:
    data = _runpod_graphql("query Pods { myself { pods { id desiredStatus } } }")
    for pod in data.get("data", {}).get("myself", {}).get("pods", []):
        if pod["id"] == RUNPOD_POD_ID:
            return pod["desiredStatus"]
    return "UNKNOWN"


def resume_pod() -> None:
    logger.info("Resuming RunPod pod %s", RUNPOD_POD_ID)
    query = """
    mutation PodResume($input: PodResumeInput!) {
      podResume(input: $input) { id desiredStatus }
    }
    """
    data = _runpod_graphql(query, {"input": {"podId": RUNPOD_POD_ID}})
    if data.get("errors"):
        messages = ", ".join(e.get("message", "") for e in data["errors"])
        raise RuntimeError(f"RunPod resume failed: {messages}")


def stop_pod() -> None:
    logger.info("Stopping RunPod pod %s", RUNPOD_POD_ID)
    query = """
    mutation PodStop($input: PodStopInput!) {
      podStop(input: $input) { id desiredStatus }
    }
    """
    _runpod_graphql(query, {"input": {"podId": RUNPOD_POD_ID}})


def _wait_for_running(timeout: int = 300) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = pod_status()
        logger.info("Pod status: %s", status)
        if status == "RUNNING":
            return True
        time.sleep(5)
    return False


def _wait_for_comfy_init() -> None:
    """Pause briefly after the pod starts so ComfyUI can finish loading models."""
    delay = max(0, COMFY_INIT_DELAY_SECONDS)
    if delay:
        logger.info("Waiting %ss for ComfyUI to finish initializing", delay)
        time.sleep(delay)


def _schedule_stop() -> None:
    if not PAUSE_AFTER_SECONDS:
        return

    def _do_stop():
        time.sleep(PAUSE_AFTER_SECONDS)
        try:
            stop_pod()
        except requests.exceptions.RequestException:
            logger.exception("Failed to stop RunPod pod")

    threading.Thread(target=_do_stop, daemon=True).start()


def _generate_with_comfy(prompt: str, output_path: Path, width: int = 1216, height: int = 704) -> Path | None:
    if not COMFY_PROXY_URL:
        logger.warning("COMFY_PROXY_URL not set; skipping ComfyUI generation")
        return None

    workflow = json.loads(json.dumps(DEFAULT_FLUX_WORKFLOW))  # deep copy
    workflow["6"]["inputs"]["text"] = prompt
    workflow["27"]["inputs"]["width"] = width
    workflow["27"]["inputs"]["height"] = height
    workflow["25"]["inputs"]["noise_seed"] = random.Random().randint(0, 1_000_000_000_000)  # nosec B311

    # Submit
    submit_resp = requests.post(
        f"{COMFY_PROXY_URL}/prompt",
        json={"prompt": workflow},
        timeout=30,
    )
    submit_resp.raise_for_status()
    submit_data = submit_resp.json()
    prompt_id = submit_data.get("prompt_id")
    if not prompt_id:
        logger.error("No prompt_id returned: %s", submit_data)
        return None
    logger.info("ComfyUI prompt submitted: %s", prompt_id)

    # Poll history
    history_url = f"{COMFY_PROXY_URL}/history/{prompt_id}"
    for attempt in range(120):
        hist_resp = requests.get(history_url, timeout=30)
        hist_resp.raise_for_status()
        hist = hist_resp.json()
        entry = hist.get(prompt_id)
        if entry and entry.get("outputs"):
            outputs = entry["outputs"]
            for node_outputs in outputs.values():
                for img in node_outputs.get("images", []):
                    filename = img["filename"]
                    subfolder = img.get("subfolder", "")
                    view_url = f"{COMFY_PROXY_URL}/view?filename={filename}&subfolder={subfolder}&type=output"
                    img_resp = requests.get(view_url, timeout=120)
                    img_resp.raise_for_status()
                    output_path.write_bytes(img_resp.content)
                    logger.info("Downloaded image from ComfyUI: %s", output_path)
                    return output_path
            # If outputs present but no images, generation may have failed
            logger.warning("ComfyUI outputs without images: %s", outputs)
            return None
        logger.debug("Polling ComfyUI history attempt %s", attempt)
        time.sleep(5)

    logger.error("ComfyUI generation timed out for prompt %s", prompt_id)
    return None




def _absolute_url(base: str, src: str) -> str | None:
    """Resolve a possibly-relative image src URL."""
    if not src:
        return None
    src = src.strip()
    if src.startswith(("http://", "https://")):
        return src
    if src.startswith("//"):
        return "https:" + src
    from urllib.parse import urljoin
    return urljoin(base, src)


def _is_usable_size(path: Path, min_width: int = 400, min_height: int = 200) -> bool:
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
    # If dimensions not in HTML, allow and check after download
    return True


def extract_article_images(url: str, item_id: str, max_candidates: int = 4) -> list[str]:
    """Download OG + article body image candidates for a URL."""
    candidates_dir = IMAGE_CANDIDATES_DIR / item_id
    candidates_dir.mkdir(parents=True, exist_ok=True)
    found: list[str] = []
    try:
        page_resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        page_resp.raise_for_status()
        html = page_resp.text
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # 1. OG image
        og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"property": "og:image"})
        if og:
            img_url = og.get("content")
            abs_url = _absolute_url(url, img_url)
            if abs_url:
                path = _download_image(abs_url, candidates_dir / "og.jpg")
                if path:
                    found.append(str(path))

        # 2. Twitter image
        if len(found) < max_candidates:
            tw = soup.find("meta", attrs={"name": "twitter:image"}) or soup.find("meta", property="twitter:image")
            if tw:
                img_url = tw.get("content")
                abs_url = _absolute_url(url, img_url)
                if abs_url:
                    path = _download_image(abs_url, candidates_dir / "twitter.jpg")
                    if path and str(path) not in found:
                        found.append(str(path))

        # 3. Article body images
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
                if path and str(path) not in found and _is_usable_size(path):
                    found.append(str(path))
    except (requests.exceptions.RequestException, OSError):
        logger.exception("Article image extraction failed for %s", url)
    return found


def _download_image(url: str, output_path: Path) -> Path | None:
    """Download an image and convert webp to jpg for preview compatibility."""
    try:
        img_resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/webp,image/apng,image/*,*/*;q=0.8"})
        img_resp.raise_for_status()
        content = img_resp.content
        if not content:
            return None
        output_path.write_bytes(content)
        # Convert webp to jpg if Pillow available
        if output_path.suffix.lower() == ".webp":
            try:
                from PIL import Image
                jpg_path = output_path.with_suffix(".jpg")
                with Image.open(output_path) as im:
                    im.convert("RGB").save(jpg_path, "JPEG")
                output_path.unlink()
                return jpg_path
            except (OSError, ValueError):
                logger.warning("Could not convert webp to jpg for %s", url)
        logger.info("Downloaded article image: %s", output_path)
        return output_path
    except (requests.exceptions.RequestException, OSError):
        logger.exception("Image download failed: %s", url)
    return None


def _fetch_og_image(url: str, output_path: Path) -> Path | None:
    try:
        page_resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        page_resp.raise_for_status()
        html = page_resp.text
        m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html, re.IGNORECASE)
        if not m:
            m = re.search(r'<meta[^>]+name="twitter:image"[^>]+content="([^"]+)"', html, re.IGNORECASE)
        if not m:
            return None
        img_url = m.group(1)
        img_resp = requests.get(img_url, timeout=20)
        img_resp.raise_for_status()
        output_path.write_bytes(img_resp.content)
        logger.info("Downloaded OG image: %s", output_path)
        return output_path
    except (requests.exceptions.RequestException, OSError):
        logger.exception("OG image fetch failed for %s", url)
    return None


def image_for_post(
    item_url: str,
    title: str,
    day: str,
    pillar: str,
    linkedin_post: str,
    hashtags: str,
    width: int = 1216,
    height: int = 704,
    skip_comfy: bool = False,
    skip_og: bool = False,
    item_id: str = "",
    force: bool = False,
) -> tuple[Path | None, str]:
    """Return a local image path for the post and its source label.

    Fallback chain:
    1. Pre-fetched article/source candidates (if item_id provided)
    2. OpenGraph image from the URL
    3. RunPod ComfyUI generated image
    4. Branded placeholder
    """
    if not item_url:
        return None, "none"
    h = _slug(title) or _slug(item_url)
    output_path = IMAGE_DIR / f"{h}.png"
    if output_path.exists() and not skip_og and not force:
        # If cached image is too small, ignore it and regenerate
        if _is_usable_size(output_path):
            return output_path, "unknown"
        logger.warning("Cached image too small, ignoring: %s", output_path)

    # 1. Use pre-downloaded article candidates if available
    if item_id and IMAGE_CANDIDATES_DIR.exists():
        candidates_dir = IMAGE_CANDIDATES_DIR / item_id
        if candidates_dir.exists():
            for cand in sorted(candidates_dir.iterdir()):
                if cand.is_file() and cand.suffix.lower() in (".jpg", ".jpeg", ".png"):
                    if not _is_usable_size(cand):
                        logger.debug("Skipping too-small candidate: %s", cand)
                        continue
                    logger.info("Using pre-fetched article image: %s", cand)
                    return cand, "article"

    # 2. Try OG image
    if not skip_og:
        og_path = output_path.with_suffix(".og.jpg")
        og = _fetch_og_image(item_url, og_path)
        if og and _is_usable_size(og):
            return og, "og"

    if skip_comfy:
        return None, "none"

    # 3. Try ComfyUI generation
    if not RUNPOD_API_KEY or not COMFY_PROXY_URL:
        logger.warning("RunPod/ComfyUI not configured")
        return None

    prompt = prompt_for_post(day, pillar, title, linkedin_post, hashtags)
    logger.info("Image prompt: %s", prompt)

    try:
        status = pod_status()
        if status != "RUNNING":
            resume_pod()
            if not _wait_for_running():
                logger.error("RunPod pod did not start in time")
                return None
            _wait_for_comfy_init()
        result = _generate_with_comfy(prompt, output_path, width=width, height=height)
        return result
    except (requests.exceptions.RequestException, OSError, RuntimeError):
        logger.exception("ComfyUI generation failed")
    finally:
        _schedule_stop()

    # 3. Final fallback: branded placeholder so every draft has an image
    logger.warning("Falling back to placeholder image for %s", title)
    placeholder = _generate_placeholder(title, output_path, width=width, height=height)
    return placeholder


if __name__ == "__main__":
    # Quick manual test
    p = image_for_post(
        item_url="https://example.com/test",
        title="AI security red team visual",
        day="Friday",
        pillar="security_signal",
        linkedin_post="Red team finding about prompt injection.",
        hashtags="#AISecurity",
        skip_comfy=False,
    )
    print("Generated:", p)