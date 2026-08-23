# Image Review — 7-Day Generated Images + Improvement Plan

**Date:** 2026-08-23
**Source files:** `.genesis/examples/7-day-generated-images.md` + 8 PNGs in `.genesis/examples/images/`
**Generator:** RunPod ComfyUI Flux workflow (flux1-dev.sft), 1024×1024

## 1. What was delivered

- 8 generated images (1 per day + 1 extra red-team visual).
- All are 1024×1024 PNG, 8-bit RGB.
- File sizes range from ~500 KB to ~1.2 MB.
- Prompts are templated per day type with a professional LinkedIn cover style.
- Brand/entity clause tries to capture AWS/Google/NVIDIA/etc. without using logos.

## 2. Quick technical audit

| Check | Result |
|-------|--------|
| All files load as PNG | ✅ |
| All same dimensions | ✅ 1024×1024 |
| No text in prompts | ✅ "No text, no words, no letters..." |
| Aspect ratio | ⚠️ 1:1 square. LinkedIn feed prefers 1.91:1 (1200×627) or 4:5 |
| File size | ⚠️ 500 KB–1.2 MB each; OK but can be larger after PNG save |
| Color profile / metadata | ⚠️ Needs verification |

## 3. Genre-by-genre review vs. top-performing LinkedIn posts

### Monday — tool_drop
**Top-post patterns:**
- High contrast, single object/hero visual, clear "what is it" signal.
- Often a product screenshot, clean UI card, or 3D render of the tool.
- Headline readability not required because the post text carries it.

**Current prompt:** "clean SaaS product UI screenshot style, dark mode dashboard, subtle neon accents, minimal"

**Feedback:**
- ✅ Good direction for B2B tool drops.
- ⚠️ Flux may hallucinate UI text or fake buttons. Add: "abstract UI wireframe, no readable text, no fake buttons, no browser chrome".
- 💡 Consider forcing a 1.91:1 landscape output for feed posts.

---

### Tuesday — viral_explained
**Top-post patterns:**
- Bold, high-energy, slightly controversial or "breaking news" visual.
- Often uses strong diagonal lines, glowing elements, speed/motion cues.
- Needs to stop the scroll in a busy feed.

**Current prompt:** "bold editorial illustration, dramatic lighting, futuristic tech visual, eye-catching headline composition"

**Feedback:**
- ✅ Strong style match.
- ⚠️ "headline composition" may encourage Flux to render fake text. Replace with "no text elements, symbolic tech breakthrough".
- 💡 Add motion/energy: "dynamic diagonal composition, light streaks, glowing neural network abstract".

---

### Wednesday — pattern_spotting
**Top-post patterns:**
- Network diagrams, connection maps, 2–3 visual elements linked together.
- Less abstract, more "this connects to that".
- Works well as infographic-style illustration.

**Current prompt:** "abstract network diagram, interconnected nodes, data flow visualization, blue and purple gradient"

**Feedback:**
- ✅ Good match.
- ⚠️ May look like generic stock AI art. Add specificity: "3 distinct layers connected by flowing data, clean labels-free diagram".
- 💡 Try a 16:9 or 1.91:1 ratio because diagrams need width.

---

### Thursday — builder_memo
**Top-post patterns:**
- Practical, relatable dev environment.
- Screenshot aesthetic, terminal, code editor, sticky notes.
- Authentic "I built this" energy.

**Current prompt:** "developer workspace aesthetic, code editor and terminal, warm desk lighting, practical engineering vibe"

**Feedback:**
- ✅ Matches builder memo tone.
- ⚠️ Code editor will almost certainly render fake code/text. Add: "blurred screen glow, no legible code, no readable text".
- 💡 Add a small human cue (hands on keyboard, coffee cup) if it does not break "no people" rule. Or relax "no people if possible" for this day type.

---

### Friday — security_signal
**Top-post patterns:**
- Dark, high-stakes, red-team/cyberpunk aesthetic.
- Shield, lock, warning amber, matrix-style binary.
- Often uses red + black or amber + black palettes.

**Current prompt:** "cybersecurity visual, digital lock, shield, red-team aesthetic, dark background with warning amber"

**Feedback:**
- ✅ Strong match.
- ⚠️ Shield/lock icons can look generic. Add: "dramatic macro shot, abstract security architecture".
- 💡 The extra `ai_security_red_team_visual.png` is a good alternative; consider A/B style variants.

---

### Saturday — founder_signal
**Top-post patterns:**
- Human-centered, founder at work, strategic planning.
- Warmer tones, office/whiteboard/laptop scenes.
- Trust and authority over hype.

**Current prompt:** "founder at laptop in modern office, strategic mood, soft natural light, business-casual, focused"

**Feedback:**
- ✅ Matches the genre.
- ⚠️ "no people if possible" conflicts with "founder at laptop". This day type **should allow people**.
- 💡 Relax the no-people rule for founder posts. Add: "diverse founder silhouette, no identifiable face".

---

### Sunday — tomorrow_in_ai
**Top-post patterns:**
- Wide horizon, future-facing, optimistic.
- Cityscapes, sunrise, abstract AI landscapes.
- Calm, reflective, thought-leadership energy.

**Current prompt:** "futuristic horizon, AI cityscape, optimistic dawn lighting, conceptual editorial illustration"

**Feedback:**
- ✅ Good match.
- ⚠️ Cityscapes can look generic. Tie it to the specific topic (e.g. Chinese lab → subtle East Asian skyline silhouette).
- 💡 Strong candidate for 1.91:1 landscape ratio.

---

## 4. Cross-cutting issues and fixes

### 4.1 Aspect ratio (critical)

LinkedIn feed images perform best at **1.91:1** (1200×627) or **4:5** (1080×1350). Current output is 1:1 square, which is suboptimal for feed reach.

**Fix options:**
- **Option A (best):** Change ComfyUI workflow to output 1216×704 or 1200×640 natively.
- **Option B (post-process):** Keep 1024×1024 and crop to 1200×627 before upload.
- **Option C (LinkedIn native):** LinkedIn accepts 1:1, but feed preview may crop. Use Option A.

**Recommendation:** Update `DEFAULT_FLUX_WORKFLOW` latent image size to **1216×704** for landscape feed images.

### 4.2 "No text" enforcement is too soft

Flux can still render glyphs/letters. Add negative prompt / stronger instruction:
- In positive prompt: repeat "completely free of text, letters, numbers, logos, watermarks, trademarks".
- In negative prompt (if workflow supports it): "text, words, letters, watermark, signature, logo, watermark, blurry".

### 4.3 People rule should be genre-specific

- Allow people for **founder_signal**, **builder_memo**, **tomorrow_in_ai**.
- Keep no people for **tool_drop**, **viral_explained**, **pattern_spotting**, **security_signal**.

### 4.4 Brand/entity clause is useful but risky

"Inspired by X aesthetic but no logos" is legally safer, but "inspired by" can still trigger brand visuals. Consider:
- Use **abstract style cues** instead of brand names.
- For AWS/Cloudflare/Google posts, describe the visual style (cloud architecture, security dashboard) without naming the company.

### 4.5 Caching / cost

Images are generated per title but not cached by source URL hash in the example run. Ensure the production `image_for_post()` checks for an existing file before waking RunPod.

### 4.6 Prompt length and truncation

`_clean_for_prompt` truncates to 240 chars. Long titles can dominate the prompt. Consider:
- Use title + first sentence of post for richer context.
- Keep title portion under 120 chars so style tokens are not pushed out.

### 4.7 Image quality consistency

Flux 1-dev at 1024×1024 produces good quality, but:
- Add seed control for reproducibility.
- Add guidance scale / steps tuning in the workflow to reduce artifacts.

---

## 5. Prompt improvement snippets

### Monday tool_drop (revised)
```
Professional LinkedIn header for a new AI tool announcement. Clean abstract SaaS dashboard, dark mode, neon accent lines, minimal composition. No text, no readable UI labels, no logos, no people. 1.91:1 aspect ratio, high detail, business-safe.
```

### Tuesday viral_explained (revised)
```
Bold editorial tech illustration for a viral AI launch. Dynamic diagonal composition, glowing abstract neural shapes, motion blur, dramatic lighting. No text, no logos, no people. High contrast, scroll-stopping, 1.91:1 aspect ratio.
```

### Wednesday pattern_spotting (revised)
```
Abstract network diagram for a LinkedIn AI pattern post. Three connected layers with flowing data lines, blue-purple gradient, clean label-free infographic style. No text, no logos, no people. 1.91:1 aspect ratio, professional.
```

### Thursday builder_memo (revised)
```
Relatable developer workspace for a practical builder tip. Laptop with soft screen glow, coffee cup, notebook, warm desk lighting. Screen content is blurred, no readable text or code. Cozy engineering vibe, no identifiable person. 1.91:1 aspect ratio.
```

### Friday security_signal (revised)
```
Dark cybersecurity editorial for an AI security post. Abstract lock-shield geometry, red-team amber glow, digital threat landscape, cinematic lighting. No text, no logos, no people. 1.91:1 aspect ratio, intense but business-safe.
```

### Saturday founder_signal (revised)
```
Human founder scene for a strategic startup post. Professional at a laptop in a modern office, soft natural light, focused strategic mood, back or side view, no identifiable face. Warm tones, 1.91:1 aspect ratio, trustworthy and calm.
```

### Sunday tomorrow_in_ai (revised)
```
Wide futuristic horizon for an AI trends post. Dawn cityscape silhouette, glowing data streams in the sky, optimistic and reflective mood. No text, no logos, no people. 1.91:1 aspect ratio, editorial illustration.
```

---

## 6. Workflow updates needed

1. **Change latent image size** from 1024×1024 to **1216×704** (or 1208×632).
2. **Add negative prompt node** if the workflow supports dual CLIP encoding.
3. **Add fixed seed option** for reproducible tests.
4. **Add filename prefix** per day type for easier organization.

---

## 7. Suggested A/B testing plan

Once improvements land:

1. Generate 2 variants per day type: **landscape 1.91:1** vs **square 1:1**.
2. Publish a small batch of each manually to LinkedIn.
3. Track 7-day engagement: impressions, clicks, reactions, comments.
4. Lock the winning aspect ratio and style per genre.

---

## 8. Priority actions

1. **P0 — Fix aspect ratio** to 1.91:1 for feed posts.
2. **P1 — Harden "no text"** with stronger prompt + negative prompt.
3. **P1 — Allow people for founder/builder posts**; keep no-people for abstract genres.
4. **P2 — Add seed + filename prefix** per day type.
5. **P2 — Cache images** by source URL hash to avoid re-generation cost.
