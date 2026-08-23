# RunPod + ComfyUI Discovery Checklist

**Goal:** Gather the exact facts needed to wire the operator's RunPod ComfyUI pod into the LinkedIn pipeline.

---

## Step 1 — Find your RunPod API key

1. Go to https://www.runpod.io/console/account
2. Click **API Keys** in the left sidebar.
3. If no key exists, click **Create API Key**.
4. Copy the key (starts with `rpa_...` or similar).
5. Save it in your password manager / 1Password / Bitwarden.
6. **Do not paste it into chat.** We will add it to the VPS `.env` later.

---

## Step 2 — Find your ComfyUI pod ID and proxy URL

1. Go to https://www.runpod.io/console/pods
2. Find the pod that runs ComfyUI.
3. Click the pod name to open its detail page.
4. Copy:
   - **Pod ID** (looks like `abc123def-ghi4-jkl5-mno6-pqrstuvwxyz`)
   - **Proxy URL** for the service that exposes port **8188** (the ComfyUI default port). It usually looks like:
     `https://pod-id-8080.proxy.runpod.net` or `https://pod-id-8188.proxy.runpod.net`
5. If you see multiple proxy URLs, the one ending in `8188` is the ComfyUI web UI.

---

## Step 3 — Confirm the pod can be paused/resumed

1. On the pod detail page, look for buttons:
   - **Pause** / **Resume** / **Start** / **Stop**
2. Try clicking **Pause** and wait 30 seconds, then click **Resume**.
3. Note:
   - How long does resume take?
   - Does the pod return to **Running** status?
   - Is it using a **Network Volume**? (shown in pod details)

---

## Step 4 — Test if ComfyUI `/prompt` endpoint is reachable

From your local machine, run:

```bash
export COMFY_PROXY_URL="https://your-pod-id-8188.proxy.runpod.net"
curl -s "$COMFY_PROXY_URL/system_stats" | head -c 500
```

Expected: JSON response with `devices`, `version`, etc.

If that works, try:

```bash
curl -s "$COMFY_PROXY_URL/history" | head -c 500
```

Expected: JSON object (possibly empty `{}`) — not an HTML error page.

If you get HTML/Cloudflare/auth error, the endpoint may be behind a login or different port.

---

## Step 5 — Export and save your default ComfyUI workflow

1. Open the ComfyUI web UI in your browser: `https://your-pod-id-8188.proxy.runpod.net`
2. Build or load the workflow you want to use for LinkedIn images.
3. In the ComfyUI UI, click **Workflow → Export (API)**.
   - This gives you the JSON format the `/prompt` endpoint accepts.
4. Save the file as `comfy_default_workflow.json` in your repo or a scratch folder.
5. Identify which node ID outputs the final image. It is usually a **SaveImage** or **PreviewImage** node. Note its node ID (e.g. `"9"` or `"SaveImage_1"`).

---

## Step 6 — Test a real image generation via API

From your local machine:

```bash
export COMFY_PROXY_URL="https://your-pod-id-8188.proxy.runpod.net"
curl -s -X POST "$COMFY_PROXY_URL/prompt" \
  -H "Content-Type: application/json" \
  -d @comfy_default_workflow.json
```

Expected: JSON response with a `prompt_id`.

Then poll:

```bash
export PROMPT_ID="the-prompt-id-from-above"
curl -s "$COMFY_PROXY_URL/history/$PROMPT_ID" | head -c 1000
```

Wait 10–60 seconds and poll again until you see `outputs` with an image filename.

Then download:

```bash
curl -s "$COMFY_PROXY_URL/view?filename=ComfyUI_00001_.png&type=output" -o test_output.png
```

Replace `ComfyUI_00001_.png` with the actual filename from the history response.

---

## Step 7 — Capture the output

After each step above, write the answers in this file or in a private note:

| Question | Answer |
|----------|--------|
| RunPod API key present? | yes / no |
| Pod ID | (write here) |
| ComfyUI proxy URL | (write here) |
| Can pause/resume via UI? | yes / no |
| Resume time estimate | (seconds/minutes) |
| `/system_stats` reachable? | yes / no |
| `/prompt` returns prompt_id? | yes / no |
| Workflow JSON file saved? | yes / no |
| Output image node ID | (write here) |
| Average generation time | (seconds) |

---

## Step 8 — Share findings back with me

Once you fill the table above, paste it here (with the Pod ID and URL redacted if you prefer). I will then:

1. Build `pipeline/image_engine.py` with RunPod pause/resume.
2. Add `image_path` to the `Draft` model.
3. Add `--with-image` to `draft-today --dry-run`.
4. Run a safe dry-run test without spending GPU credits.
5. Only after dry-run passes, do a single real image generation test.

