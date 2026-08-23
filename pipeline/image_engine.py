"""Image generation and selection for LinkedIn posts.

Supports two sources:
1. Source article OpenGraph / Twitter image (free, fast).
2. RunPod ComfyUI pod (on-demand GPU, automatic pause/resume).

Images are stored under DATA_DIR/images/ and referenced from Draft.image_path.
"""
import logging
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from config.settings import DATA_DIR
from pipeline.storage import url_hash

logger = logging.getLogger(__name__)

RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY", "")
RUNPOD_POD_ID = os.getenv("RUNPOD_POD_ID", "")
COMFY_PROXY_URL = os.getenv("COMFY_PROXY_URL", "")
COMFY_WORKFLOW_PATH = os.getenv("COMFY_WORKFLOW_PATH", "")
PAUSE_AFTER_SECONDS = int(os.getenv("PAUSE_AFTER_SECONDS", "300"))

IMAGE_DIR = DATA_DIR / "images"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)


def _graphql(query: str) -> dict:
    resp = requests.post(
        "https://api.runpod.io/graphql",
        headers={"Authorization": f"Bearer {RUNPOD_API_KEY}"},
        json={"query": query},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_pod_status() -> str:
    """Return RunPod pod desiredStatus (RUNNING, PAUSED, EXITED, etc.)."""
    data = _graphql(
        'query Pod { myself { pods(id: "' + RUNPOD_POD_ID + '") { id desiredStatus } } }'
    )
    pods = data.get("data", {}).get("myself", {}).get("pods", [])
    if not pods:
        raise RuntimeError(f"Pod {RUNPOD_POD_ID} not found")
    return pods[0].get("desiredStatus", "UNKNOWN")


def resume_pod() -> None:
    _graphql('mutation PodResume { podResume(id: "' + RUNPOD_POD_ID + '") { id desiredStatus } }')
    logger.info("Requested resume for pod %s", RUNPOD_POD_ID)


def pause_pod() -> None:
    _graphql('mutation PodPause { podPause(id: "' + RUNPOD_POD_ID + '") { id desiredStatus } }')
    logger.info("Requested pause for pod %s", RUNPOD_POD_ID)


def wait_for_pod_running(timeout: int = 300, poll_interval: int = 5) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = get_pod_status()
        if status == "RUNNING":
            return True
        logger.info("Pod status %s; waiting...", status)
        time.sleep(poll_interval)
    return False


def fetch_og_image(url: str) -> Path | None:
    """Download the source page's OpenGraph or Twitter image if available."""
    try:
        page = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"}).text
        import re

        m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', page, re.IGNORECASE)
        if not m:
            m = re.search(r'<meta[^>]+name="twitter:image"[^>]+content="([^"]+)"', page, re.IGNORECASE)
        if not m:
            return None
        img_url = m.group(1)
        ext = Path(urlparse(img_url).path).suffix or ".jpg"
        if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
            ext = ".jpg"
        dest = IMAGE_DIR / f"{url_hash(url)}_og{ext}"
        r = requests.get(img_url, timeout=20)
        r.raise_for_status()
        dest.write_bytes(r.content)
        logger.info("Fetched OG image for %s -> %s", url, dest)
        return dest
    except Exception:
        logger.exception("OG image fetch failed for %s", url)
    return None


def _load_default_workflow() -> dict | None:
    if not COMFY_WORKFLOW_PATH:
        return None
    p = Path(COMFY_WORKFLOW_PATH)
    if not p.exists():
        logger.warning("ComfyUI workflow file not found: %s", p)
        return None
    import json

    return json.loads(p.read_text())


def _inject_prompt_into_workflow(workflow: dict, prompt_text: str) -> dict:
    """Best-effort prompt injection for common CLIPTextEncode nodes."""
    wf = dict(workflow)
    for node in wf.values():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type", "")
        if "CLIPTextEncode" in class_type:
            inputs = node.setdefault("inputs", {})
            if "text" in inputs:
                inputs["text"] = prompt_text
                break
    return wf


def generate_via_comfy(workflow_json: dict, output_path: Path, timeout: int = 600) -> Path | None:
    """Submit a ComfyUI workflow to the running pod and download the result."""
    if not COMFY_PROXY_URL:
        logger.error("COMFY_PROXY_URL not set")
        return None

    prompt_url = f"{COMFY_PROXY_URL.rstrip('/')}/prompt"
    resp = requests.post(prompt_url, json={"prompt": workflow_json}, timeout=30)
    resp.raise_for_status()
    prompt_id = resp.json().get("prompt_id")
    if not prompt_id:
        logger.error("ComfyUI did not return a prompt_id")
        return None

    history_url = f"{COMFY_PROXY_URL.rstrip('/')}/history/{prompt_id}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            hist = requests.get(history_url, timeout=30).json()
            entry = hist.get(prompt_id, {})
            outputs = entry.get("outputs", {})
            if outputs:
                for node_outputs in outputs.values():
                    for img in node_outputs.get("images", []):
                        filename = img["filename"]
                        subfolder = img.get("subfolder", "")
                        view_url = (
                            f"{COMFY_PROXY_URL.rstrip('/')}/view"
                            f"?filename={filename}&subfolder={subfolder}&type=output"
                        )
                        r = requests.get(view_url, timeout=60)
                        r.raise_for_status()
                        output_path.write_bytes(r.content)
                        logger.info("Downloaded ComfyUI output %s", output_path)
                        return output_path
        except Exception:
            logger.exception("Error polling ComfyUI history")
        time.sleep(5)

    logger.error("ComfyUI generation timed out for prompt %s", prompt_id)
    return None


def _schedule_pause() -> None:
    """Schedule pod pause after PAUSE_AFTER_SECONDS in a daemon thread."""
    import threading

    def _pause() -> None:
        time.sleep(PAUSE_AFTER_SECONDS)
        try:
            pause_pod()
        except Exception:
            logger.exception("Scheduled pod pause failed")

    threading.Thread(target=_pause, daemon=True).start()


def image_for_post(
    url: str,
    prompt_text: str,
    prefer_source_image: bool = True,
    workflow_json: dict | None = None,
) -> Path | None:
    """Return a local image path for a post, using source OG or ComfyUI.

    Order:
      1. Cached image (any existing file for this URL).
      2. Source OpenGraph image if prefer_source_image is True.
      3. RunPod ComfyUI generation.

    The RunPod pod is resumed if needed and paused after a grace period.
    """
    h = url_hash(url)
    existing = sorted(IMAGE_DIR.glob(f"{h}*"))
    if existing:
        return existing[0]

    if prefer_source_image:
        og = fetch_og_image(url)
        if og:
            return og

    # RunPod / ComfyUI path
    if not RUNPOD_API_KEY or not RUNPOD_POD_ID or not COMFY_PROXY_URL:
        logger.warning("RunPod ComfyUI not fully configured; skipping generation")
        return None

    wf = workflow_json or _load_default_workflow()
    if not wf:
        logger.warning("No ComfyUI workflow provided and no default configured")
        return None
    wf = _inject_prompt_into_workflow(wf, prompt_text)
    output_path = IMAGE_DIR / f"{h}.png"

    try:
        status = get_pod_status()
        if status != "RUNNING":
            resume_pod()
            if not wait_for_pod_running():
                logger.error("RunPod pod did not reach RUNNING state")
                return None
        result = generate_via_comfy(wf, output_path)
        return result
    finally:
        _schedule_pause()


def build_image_prompt(post_type: str, title: str, summary: str) -> str:
    """Create a simple prompt for ComfyUI based on the post content."""
    return (
        f"A clean, editorial illustration for a LinkedIn post about AI builders. "
        f"Style: minimal, modern, tech-forward, no text, no logos. "
        f"Topic: {title}. Context: {summary[:200]}"
    )
