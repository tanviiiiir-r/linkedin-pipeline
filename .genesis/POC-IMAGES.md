# POC Research — Images for LinkedIn Posts

**Date:** 2026-08-23
**Goal:** Find a reliable, low-cost way to attach images to LinkedIn posts published by the pipeline.

## 1. What the pipeline currently supports

- `pipeline/publishers/linkedin.py` publishes via LinkedIn UGC Posts API v2.
- Current payload uses `"shareMediaCategory": "NONE"` (text-only post).
- The `Draft` model has no image field today.
- Instagram collector already fetches media URLs, but they are not reused for LinkedIn publishing.

## 2. LinkedIn native image upload options

LinkedIn offers two relevant API paths for free personal OAuth apps:

### 2a. UGC Posts with an existing image URL (simpler, but limited)
The legacy UGC Posts API supports `shareMediaCategory: "ARTICLE"` with a `media` array where each entry can reference a remote URL. However:
- Remote URLs must be publicly reachable and return an image content type.
- LinkedIn may unfurl/crawl the URL; it is not a guaranteed image attachment.
- This is the easiest path for **link-preview cards**, not true inline images.

### 2b. Upload image asset first, then reference by URN (robust)
The recommended flow:
1. Call `POST /v2/assets?action=registerUpload` to get an upload URL and a digital-media asset URN.
2. `PUT` the image binary to the upload URL.
3. Wait for the asset to be processed.
4. Publish a UGC post with `shareMediaCategory: "IMAGE"` and the asset URN in `media`.

Required OAuth scope: `w_member_social` (already in default scopes).

Image constraints:
- Format: JPEG, PNG, GIF
- Max file size: 8 MB
- Max resolution: 36,000,000 pixels total
- Aspect ratio: 1.91:1 or 1:1 recommended for feed

### 2c. Rich media / article / video
- `VIDEO` requires the same upload flow plus transcoding; heavier.
- `ARTICLE` is for external links with a preview card.
- For this POC, **IMAGE upload (2b)** is the sweet spot.

## 3. Where do images come from?

| Source | Cost | Pros | Cons |
|--------|------|------|------|
| **Source article OpenGraph image** | Free | Relevant to content | Often missing, wrong aspect ratio, branded, copyrighted |
| **Unsplash / Pexels API** | Free | High quality, CC0 | Generic, not tied to the specific signal |
| **AI image generation (Ollama/local SD or DALL-E / Ideogram / FLUX)** | Local=compute only; APIs=credits | Custom, can match post concept | Adds latency/cost; needs prompt engineering; quality varies |
| **Manual upload by operator** | Human time | Highest quality/approval | Breaks automation |

## 4. Recommended POC architecture

For a quick, low-risk proof-of-concept:

1. **Image source:** source article OpenGraph image + AI-generated fallback.
   - Try to extract `og:image` or `twitter:image` from the source URL.
   - If missing or low-quality, generate a simple branded image locally or via a cheap API.
2. **Image type:** single JPEG/PNG, 1200×630 (1.91:1) or 1080×1080 (1:1).
3. **Storage:** save downloaded/generated images to `DATA_DIR/images/` keyed by item hash.
4. **Publishing:** implement asset upload in `DirectLinkedInPublisher` and set `shareMediaCategory: "IMAGE"`.
5. **Approval gate:** show the image in the dry-run / approval view so the operator can reject bad images before publish.

## 5. Implementation sketch

```python
# New file: pipeline/image_engine.py
from pathlib import Path
from urllib.parse import urlparse
import requests

IMAGE_DIR = DATA_DIR / "images"

def fetch_og_image(url: str) -> Path | None:
    """Download the source page's OpenGraph image if available."""
    try:
        page = requests.get(url, timeout=15).text
        import re
        m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', page)
        if not m:
            m = re.search(r'<meta[^>]+name="twitter:image"[^>]+content="([^"]+)"', page)
        if m:
            img_url = m.group(1)
            ext = Path(urlparse(img_url).path).suffix or ".jpg"
            dest = IMAGE_DIR / f"{url_hash(url)}{ext}"
            r = requests.get(img_url, timeout=20)
            r.raise_for_status()
            dest.write_bytes(r.content)
            return dest
    except Exception:
        logger.exception("OG image fetch failed for %s", url)
    return None

def generate_image(prompt: str, output_path: Path) -> Path | None:
    """Generate an image via local Ollama-compatible image model or configured provider."""
    # TBD: integrate with Ollama / Stable Diffusion / DALL-E
    return None
```

```python
# Extend Draft model in pipeline/drafting.py
class Draft(BaseModel):
    ...
    image_path: Path | None = None  # local path to the chosen image

# Extend DirectLinkedInPublisher.publish in pipeline/publishers/linkedin.py
if draft.image_path:
    asset_urn = self._upload_image_asset(draft.image_path)
    payload["specificContent"]["com.linkedin.ugc.ShareContent"]["shareMediaCategory"] = "IMAGE"
    payload["specificContent"]["com.linkedin.ugc.ShareContent"]["media"] = [{
        "status": "READY",
        "description": {"text": draft.title},
        "media": asset_urn,
        "title": {"text": draft.title},
    }]
```

## 6. Open questions to resolve

1. **Does the operator want AI-generated images, source OpenGraph images, or both?**
2. **Budget:** local Ollama image models (e.g. Stable Diffusion via Ollama) = free after setup; API = per-image cost.
3. **Brand safety:** should every image be approved in the dry-run view before publish?
4. **Aspect ratio:** 1200×630 landscape for feed, or 1080×1080 square?
5. **Fallback policy:** if image fetch/generation fails, publish text-only or block the post?

## 7. Suggested next step

Build a **narrow POC**:
1. Add `image_path` to `Draft`.
2. Implement `fetch_og_image()` for source URLs.
3. Add `--image` support to `publish` dry-run so the operator sees the chosen image.
4. Add `_upload_image_asset()` only to `DirectLinkedInPublisher` behind a feature flag.
5. Demo: `python run.py draft-today --dry-run --with-image` shows the image path LinkedIn would use.

This keeps the human approval gate intact while proving the image path end-to-end without spending API credits.
