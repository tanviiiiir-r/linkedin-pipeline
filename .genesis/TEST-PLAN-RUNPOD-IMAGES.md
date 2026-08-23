# Test Plan — RunPod ComfyUI Image Integration

**Branch:** `codex/runpod-image-poc`  
**Goal:** Verify the image engine works end-to-end before merging to `main`.  
**Tester:** Hermes agent on VPS  
**Last updated:** 2026-08-23

---

## 1. Environment setup (one-time)

On the VPS, inside the project directory, create or edit `.env`:

```bash
# Required for ComfyUI / RunPod control
RUNPOD_API_KEY=rpa_...                       # from https://www.runpod.io/console/account
RUNPOD_POD_ID=z5hmv5qe1n0ary                 # provided by operator
COMFY_PROXY_URL=https://your-pod-id-8188.proxy.runpod.net   # from RunPod pod UI
COMFY_WORKFLOW_PATH=/opt/linkedin-pipeline/data/comfy_default_workflow.json
PAUSE_AFTER_SECONDS=300

# Existing required vars (confirm they are still set)
LLM_PROVIDER=ollama
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=...                                # whatever model is pulled locally
MCP_AUTH_TOKEN=...
```

Then copy the ComfyUI workflow JSON to the path above:

```bash
scp comfy_default_workflow.json root@186.241.23.161:/opt/linkedin-pipeline/data/
```

---

## 2. Pre-test checks

Run these on the VPS inside the project directory:

```bash
cd /opt/linkedin-pipeline
git fetch origin
git checkout codex/runpod-image-poc
python -m pytest tests/ -q
ruff check .
```

Expected:
- `41 passed`
- `All checks passed!`

---

## 3. Test matrix

### Test A — Dry-run without images (regression)

```bash
python run.py draft-today --dry-run --allow-raw --limit 1
```

**Pass criteria:**
- Post text is printed.
- No `Image:` line appears.
- No RunPod API calls are made.
- Exit code `0`.

---

### Test B — OpenGraph image fetch (safe, no GPU spend)

```bash
python run.py draft-today --dry-run --with-image --allow-raw --limit 1
```

**Pass criteria:**
- `Image:` line is printed with a path under `data/images/`.
- File exists and is a valid image:
  ```bash
  file data/images/*
  ```
- File size > 1 KB and dimensions > 500 px in at least one axis.
- No RunPod API calls are made.
- Exit code `0`.

---

### Test C — RunPod pod status query (no state change)

```bash
python - <<'PY'
from pipeline.image_engine import get_pod_status
print(get_pod_status())
PY
```

**Pass criteria:**
- Prints one of: `RUNNING`, `PAUSED`, `EXITED`, `TERMINATED`.
- No error.
- Note the starting status for the next test.

---

### Test D — Resume pod + ComfyUI generation (GPU spend)

> ⚠️ This test will spend RunPod GPU credits. Run only during cheap off-peak hours or with a low-tier GPU.

```bash
python run.py draft-today --dry-run --with-image --force-comfy --allow-raw --limit 1
```

**Pass criteria:**
- Pod transitions from `PAUSED`/`EXITED` to `RUNNING` within 5 minutes.
- ComfyUI workflow is submitted and an image is downloaded.
- `Image:` line points to a PNG under `data/images/`.
- Downloaded file is a valid PNG > 10 KB.
- Pod pauses automatically within `PAUSE_AFTER_SECONDS` (default 300s) after generation completes.
- Exit code `0`.

---

### Test E — Image caching / duplicate suppression

Run Test B twice for the same source URL.

**Pass criteria:**
- Second run reuses the same image file (no duplicate new file for the same URL).
- No second network fetch for the OG image.

---

### Test F — Dry-run with `--allow-raw` removed (no worthy items)

```bash
python run.py draft-today --dry-run --with-image --limit 1
```

**Pass criteria:**
- Prints `No items to draft. Run collect and score first, or use --allow-raw.`
- Exit code `1`.
- No images downloaded, no RunPod calls.

---

## 4. Failure investigation commands

If a test fails, capture:

```bash
# Pod status
curl -s -X POST https://api.runpod.io/graphql \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "query Pod { myself { pods(id: \"z5hmv5qe1n0ary\") { id desiredStatus costPerHr } } }"}' | jq

# ComfyUI reachability
curl -s "$COMFY_PROXY_URL/system_stats" | head -c 500
curl -s "$COMFY_PROXY_URL/history" | head -c 500

# Local logs
tail -n 100 data/*.log
```

---

## 5. Approval / merge gates

Before merging `codex/runpod-image-poc` to `main`:

- [ ] Tests A, B, F pass (no GPU spend).
- [ ] Test C passes (RunPod API key works).
- [ ] Test D passes at least once (full image generation path proven).
- [ ] Test E passes (caching works).
- [ ] Branch is rebased on latest `origin/main`.
- [ ] `python -m pytest tests/` green on branch.
- [ ] `ruff check .` clean on branch.
- [ ] Operator confirms image quality and pause/resume cost are acceptable.

---

## 6. Next steps after merge

1. Add LinkedIn asset-upload path to `DirectLinkedInPublisher`:
   - `registerUpload` → `PUT` image → `shareMediaCategory: IMAGE`.
2. Add image preview to approval view (`cmd_queue`, `cmd_approve`, or a new `review` command).
3. Decide default policy: OG image first, or always ComfyUI, or per day-type.
