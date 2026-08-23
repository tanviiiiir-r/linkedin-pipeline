# POC Research — RunPod ComfyUI Image Generation for LinkedIn Posts

**Date:** 2026-08-23
**Goal:** Use the operator's existing RunPod ComfyUI pod to generate post images on demand, with automatic pause/resume to save GPU credits.

## 1. The operator's setup

- **RunPod account** with a ComfyUI pod already configured.
- **Desired behavior:**
  1. Pipeline decides an image is needed.
  2. Deploy/resume the RunPod pod if it is paused/stopped.
  3. Activate a ComfyUI workflow via the RunPod serverless or proxy endpoint.
  4. Download the generated image.
  5. Pause the pod when idle to stop burning GPU credits.

## 2. RunPod control options

RunPod exposes a **GraphQL API** for managing pods:

| Action | GraphQL mutation / query |
|--------|--------------------------|
| List pods | `query Pods { myself { pods { id name imageName env runtime costPerHr gpuCount desiredStatus } } }` |
| Resume pod | `mutation PodResume { podResume(id: "pod-id") { id desiredStatus } }` |
| Pause pod | `mutation PodPause { podPause(id: "pod-id") { id desiredStatus } }` |
| Stop pod | `mutation PodStop { podStop(id: "pod-id") { id desiredStatus } }` |

Authentication: `Authorization: Bearer <RUNPOD_API_KEY>`.

Endpoint: `https://api.runpod.io/graphql`.

Docs: https://docs.runpod.io/graphql

## 3. ComfyUI workflow activation on RunPod

RunPod ComfyUI pods can be exposed in two ways:

### 3a. Network volume + persistent pod (serverful)
- Pod has a persistent network volume with ComfyUI installed.
- You connect directly to the pod's proxy URL (e.g. `https://pod-id-8080.proxy.runpod.net/`).
- You can send a ComfyUI workflow JSON to `/prompt` and poll `/history` or listen on WebSocket for completion.
- Requires the pod to be **RUNNING** before sending the prompt.

### 3b. RunPod Serverless (pay-per-job)
- Package the ComfyUI workflow as a serverless worker.
- Call it via HTTP; RunPod spins up a GPU only for the job, then shuts it down.
- No pause/resume logic needed because you pay only for the cold-start + execution time.
- More setup initially; cheaper for sporadic generation.

**For the operator's current setup (existing ComfyUI pod), 3a is the path of least resistance**, but requires pause/resume orchestration.

## 4. End-to-end flow

```text
Pipeline needs image
       |
       v
Check pod status via RunPod GraphQL
       |
       +-- RUNNING -->   Send ComfyUI workflow to pod /prompt endpoint
       +-- PAUSED/STOPPED -->  PodResume --> poll until RUNNING --> send workflow
       |
       v
Poll /history or WebSocket until image is done
       |
       v
Download image from pod's output URL
       |
       v
Save to DATA_DIR/images/
       |
       v
Schedule PodPause after a short grace period (e.g. 5 min)
```

## 5. Proposed module: `pipeline/image_engine.py` extended for RunPod ComfyUI

```python
"""Image generation via RunPod ComfyUI pod."""
import logging
import time
from pathlib import Path

import requests

from config.settings import DATA_DIR, LLM_TIMEOUT

logger = logging.getLogger(__name__)

RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY", "")
RUNPOD_POD_ID = os.getenv("RUNPOD_POD_ID", "")
COMFY_PROXY_URL = os.getenv("COMFY_PROXY_URL", "")  # e.g. https://pod-id-8080.proxy.runpod.net
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
    data = _graphql(f"""
    query Pod {{
        myself {{
            pods(id: "{RUNPOD_POD_ID}") {{
                id
                desiredStatus
            }}
        }}
    }}
    """)
    return data["data"]["myself"]["pods"][0]["desiredStatus"]


def resume_pod() -> None:
    _graphql(f"""
    mutation PodResume {{
        podResume(id: "{RUNPOD_POD_ID}") {{
            id
            desiredStatus
        }}
    }}
    """)


def pause_pod() -> None:
    _graphql(f"""
    mutation PodPause {{
        podPause(id: "{RUNPOD_POD_ID}") {{
            id
            desiredStatus
        }}
    }}
    """)


def wait_for_pod_running(timeout: int = 300) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = get_pod_status()
        if status == "RUNNING":
            return True
        time.sleep(5)
    return False


def generate_image(workflow_json: dict, output_path: Path) -> Path | None:
    """Send a ComfyUI workflow to the running pod and download the result."""
    if not COMFY_PROXY_URL:
        logger.error("COMFY_PROXY_URL not set")
        return None

    # Submit prompt
    prompt_url = f"{COMFY_PROXY_URL}/prompt"
    resp = requests.post(prompt_url, json={"prompt": workflow_json}, timeout=30)
    resp.raise_for_status()
    prompt_id = resp.json()["prompt_id"]

    # Poll history
    history_url = f"{COMFY_PROXY_URL}/history/{prompt_id}"
    for _ in range(120):
        hist = requests.get(history_url, timeout=30).json()
        if prompt_id in hist and hist[prompt_id].get("outputs"):
            outputs = hist[prompt_id]["outputs"]
            # Download first output image
            for node_id, node_outputs in outputs.items():
                for img in node_outputs.get("images", []):
                    filename = img["filename"]
                    subfolder = img.get("subfolder", "")
                    view_url = f"{COMFY_PROXY_URL}/view?filename={filename}&subfolder={subfolder}&type=output"
                    r = requests.get(view_url, timeout=60)
                    r.raise_for_status()
                    output_path.write_bytes(r.content)
                    return output_path
        time.sleep(5)
    logger.error("ComfyUI generation timed out for prompt %s", prompt_id)
    return None


def image_for_post(prompt_text: str, url_hash: str, workflow_json: dict | None = None) -> Path | None:
    """Resume pod, generate image, pause pod."""
    if not RUNPOD_API_KEY or not RUNPOD_POD_ID:
        logger.warning("RunPod not configured")
        return None

    output_path = IMAGE_DIR / f"{url_hash}.png"
    if output_path.exists():
        return output_path

    try:
        if get_pod_status() != "RUNNING":
            resume_pod()
            if not wait_for_pod_running():
                logger.error("RunPod pod did not start in time")
                return None

        # Optionally build workflow JSON from prompt_text if not provided
        wf = workflow_json or _default_workflow(prompt_text)
        result = generate_image(wf, output_path)
        return result
    finally:
        # Pause after grace period in a background thread or lightweight scheduler
        _schedule_pause()


def _schedule_pause():
    """Schedule pod pause after PAUSE_AFTER_SECONDS."""
    import threading
    def _pause():
        time.sleep(PAUSE_AFTER_SECONDS)
        pause_pod()
    threading.Thread(target=_pause, daemon=True).start()
```

## 6. Cost and safety considerations

- **Resume cost:** you pay for the time the pod is RUNNING. Pausing stops billing for GPU but may keep storage/network-volume charges.
- **Cold-start time:** resuming a paused pod can take 30–120 seconds depending on image size and network volume.
- **Race condition:** if two image requests arrive close together, the second one might trigger a pause while the first is still generating. Use a small in-memory lock or a single scheduler thread.
- **Fallback:** if RunPod is unreachable, fall back to OpenGraph image fetch or text-only post.
- **Approval gate:** show the generated image during dry-run / approval so the operator can reject it.

## 7. Required secrets

Add to `.env` on the VPS:

```bash
RUNPOD_API_KEY=...
RUNPOD_POD_ID=...
COMFY_PROXY_URL=https://your-pod-id-8080.proxy.runpod.net
PAUSE_AFTER_SECONDS=300
```

## 8. Open questions

1. Does the operator's ComfyUI pod already expose a `/prompt` endpoint, or is it behind RunPod's serverless wrapper?
2. Which workflow should be the default? (portrait/landscape, branded style, text-on-image?)
3. Does the operator want to generate one image per post, or only for specific day types?
4. Preferred pause delay after generation? (5 min is a safe default.)
5. Should generated images be cached by URL hash so the same source article reuses the same image?

## 9. Suggested POC scope

A minimal end-to-end POC:
1. Add `image_path` to `Draft`.
2. Create `pipeline/image_engine.py` with RunPod + ComfyUI support.
3. Add a `--with-image` flag to `draft-today` that calls `image_for_post()`.
4. Dry-run mode shows `[IMAGE] path/to/generated.png` without spending RunPod credits.
5. Manual test: resume pod, generate one image, pause pod.
6. LinkedIn publishing with images is deferred until after the image path is proven.

This keeps the human approval gate and avoids paying for GPU until the operator explicitly triggers a real run.
