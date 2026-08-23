# RunPod + ComfyUI Discovery Answers

**Date:** 2026-08-23
**Operator:** rtanvir290
**Pod ID:** z5hmv5qe1n0ary
**Connection:** RunPod connected through Composio

## Known facts

- Pod ID: `z5hmv5qe1n0ary`
- RunPod account: `rtanvir290`
- Integration: Composio (not direct GraphQL API key yet)

## Unknowns we still need

1. Is this a **persistent pod** or a **RunPod serverless endpoint** in Composio?
2. What is the **ComfyUI proxy URL** (or Composio action name) for this pod?
3. Can we control pause/resume through **Composio actions**, or do we still need a direct RunPod API key?
4. Which **Composio app** is used — `runpod` or `comfyui`?

## Next steps to discover

### Option A — Direct RunPod GraphQL

1. Go to https://www.runpod.io/console/account → API Keys.
2. Create an API key.
3. Test from local terminal:
   ```bash
   export RUNPOD_API_KEY="rpa_..."
   curl -s -X POST https://api.runpod.io/graphql \
     -H "Authorization: Bearer $RUNPOD_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"query": "query Pods { myself { pods { id desiredStatus } } }"}' | jq
   ```
4. Confirm pod `z5hmv5qe1n0ary` appears and note `desiredStatus`.
5. Try resume/pause mutations from the research doc to confirm control.

### Option B — Via Composio actions

1. Go to https://app.composio.io → Connections / Apps.
2. Find the connected RunPod or ComfyUI app.
3. List available actions and look for:
   - `RUNPOD_RESUME_POD`
   - `RUNPOD_PAUSE_POD`
   - `RUNPOD_GET_POD_STATUS`
   - `COMFYUI_RUN_WORKFLOW`
   - `COMFYUI_GET_OUTPUT`
4. Test one action through Composio playground or API.
5. Note whether you need a direct RunPod API key in addition to Composio.

### Option C — Get the pod proxy URL from RunPod UI

1. Go to https://www.runpod.io/console/pods
2. Click pod `z5hmv5qe1n0ary`.
3. Copy the **Connect** URL for port 8188 (ComfyUI).
4. If the pod is RUNNING, test:
   ```bash
   curl -s https://pod-id-8188.proxy.runpod.net/system_stats | head -c 500
   ```
5. If it works, ComfyUI `/prompt` and `/history` should also work.

