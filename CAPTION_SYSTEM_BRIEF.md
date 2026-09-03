# LinkedIn Caption System — Deep Technical Brief

> Scope: how the pipeline produces the text that becomes the LinkedIn post (internally called `linkedin_post`).

---

## 1. What "caption" means in this pipeline

There is no separate `caption` field. The LinkedIn caption **is** the `linkedin_post` field inside the `Draft` model. Everything else (`short_pill`, `forward_pill`, `narrative_pill`, `newsletter_section`, `hashtags`) is derived from or alongside it.

| Field | File / model | Role |
|---|---|---|
| `linkedin_post` | `pipeline/drafting.py` `Draft` | The actual LinkedIn caption/body text |
| `hashtags` | `Draft` | Tags appended to the post |
| `newsletter_section` | `Draft` | Longer markdown version for the weekly newsletter |
| `short_pill` | `Draft` | 1-2 sentence takeaway |
| `forward_pill` | `Draft` | "What this enables next" angle |
| `narrative_pill` | `Draft` | Story-first version |

A Draft is serialized as a YAML-frontmatter markdown file in `data/queue/`, e.g.:

```markdown
---
item_id: e82667920f5e
pillar: builder_memo
title: How accurate have Ed Zitron's AI skeptic predictions been?
source_url: https://danluu.com/zitron/
hashtags: #Reasoning, #LlmApps, #SecureAI
---

## LinkedIn Post
Builder memo: ...

## Newsletter Section
...

## Short Pill
...
```

---

## 2. Two generators: rule-based vs LLM-based

The repo has **two independent caption generators**. They are not composed; one is chosen per draft.

### 2.1 Rule-based drafter — `pipeline/drafting.py::draft_item()`

This is the **default fallback** and, currently, the path used by `cmd_daily`.

It builds the caption from a fixed template:

```python
hook = _PILLAR_HOOKS.get(pillar, "AI signal")

linkedin_post = f"""{hook}: {title}

What changed: {why[:240]}

Why builders should care: this is the kind of signal that shifts how we design, deploy, and secure AI systems. Watch it, experiment with it, and share what breaks.

Read more: {url}

{" ".join(tags)}""".strip()
```

**Template pieces:**
- `hook`: depends on `pillar` (the day’s `post_type`):
  - `tool_drop` → "New tool alert"
  - `viral_explained` → "Why this matters for AI builders"
  - `pattern_spotting` → "Pattern worth watching"
  - `builder_memo` → "Builder memo"
  - `tomorrow_in_ai` → "Tomorrow in AI"
  - default → "AI signal"
- `why`: first of 2–3 extracted "claims" from `raw_content`, or `summary`, or `item_title`
- `tags`: from `hashtags_from_topics(score.topics)` or pillar defaults

**Pros:** deterministic, fast, no API cost.
**Cons:** repetitive, generic second paragraph, often sounds AI-generated, doesn't deeply use the source.

### 2.2 LLM-based drafter — `pipeline/drafting_v2.py::draft_item_v2()`

This is the **intended humanized path**. It calls the configured LLM (`pipeline/llm_client.py`).

**Prompt architecture:**

```
SYSTEM:
{voice.persona}
Tone: {', '.join(voice.tone)}.
Today's job ({day_plan.day_name}, {day_plan.post_type}): {day_plan.job}.
Never use these words or phrases: {voice.no_go_words}.
Keep the LinkedIn post under {voice.max_words[post_type]} words.
End with this discussion prompt or a natural variant of it: {voice.cta_by_day[post_type]}.
Output only valid JSON with keys: linkedin_post, newsletter_section, short_pill, forward_pill, narrative_pill, hashtags.
hashtags must be a list of strings starting with #.

USER:
Day plan: {day_plan.day_name} — {day_plan.post_type}: {day_plan.job}
Source title: {item.item_title}
Source URL: {item.item_url}
Primary topic: {score.primary_topic or topics or 'general'}
Confidence: {score.pillar_confidence}% | Signal strength: {score.signal_strength}%
Pillar: {score.pillar or day_plan.post_type}
Summary:
{item.summary or item.raw_content[:800]}
Key claims:
- ...
Preferred sources for this day: {', '.join(day_plan.source_bias)}.
Draft the post and return valid JSON only.
```

**Supported LLM providers** (`config/settings.py` + `pipeline/llm_client.py`):
- `ollama` (default, local, at `http://127.0.0.1:11434/v1`)
- `openai`
- `anthropic`

Env vars: `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`.

**Output parsing:** `_safe_json()` strips markdown fences, tolerates trailing punctuation, and falls back to regex extraction of the first `{...}` block. `_hydrate_draft()` then turns the parsed dict into a Pydantic `Draft`.

**Fallback:** if `is_available()` is false, JSON is malformed, or schema validation fails, it falls back to `draft_item(item, score)` (rule-based).

---

## 3. Which generator actually runs?

`cmd_daily` in `pipeline/hermes.py` currently does:

```python
for item in worthy_items:
    score = score_item(item)
    draft = draft_item(item, score)          # <-- rule-based
    # ... generate images ...
```

**It does NOT call `draft_item_v2()`**. So today's live drafts are all rule-based, even though the LLM drafter exists.

`draft_item_v2()` is only invoked if a caller explicitly uses it (e.g. `draft_for_day()` in scripts, or the old `cmd_draft` path).

---

## 4. Post-processing / hydration of the caption

After generation, `_hydrate_draft()` in `drafting_v2.py` mutates the caption:

1. **Source URL injection.** If `item.item_url` is not already in the post, appends:
   ```
   Read more: {item.item_url}
   ```
2. **Founder-signal question enforcement.** If `post_type == "founder_signal"` and the post doesn't end with `?`, appends the configured CTA question.
3. **Newsletter padding.** If `newsletter_section` is < 80 words, appends a generic "Why this matters now" paragraph.
4. **Hashtag normalization.** Ensures every tag starts with `#`, removes duplicates, defaults from `DayPlan.hashtag_set` if missing.

Rule-based `draft_item()` does equivalent steps inside its own template but does not inject a founder question.

---

## 5. Voice configuration

Voice lives in `pipeline/voice.py` as a single `DEFAULT_VOICE`. There is no per-day override yet.

Key controls:
- `persona`: builder colleague tone
- `tone`: direct, conversational, skeptical when hype is high
- `no_go_words`: banned AI-buzzwords (`game-changer`, `leverage`, `synergy`, etc.)
- `max_words`: per-post-type caps (200–260)
- `cta_by_day`: per-post-type discussion prompt
- `signature_phrases`: reusable lines (currently not injected automatically)

---

## 6. Editorial calendar influence

`config/calendar.py` maps each weekday to a `DayPlan`:

| Day | `post_type` | `job` | Word cap from Voice |
|---|---|---|---|
| Monday | `tool_drop` | New tool/API/repo with one-liner | 200 |
| Tuesday | `viral_explained` | Translate trending signal | 220 |
| Wednesday | `pattern_spotting` | Connect 2–3 signals | 240 |
| Thursday | `builder_memo` | Practical trick | 200 |
| Friday | `security_signal` | AI security/red-team | 220 |
| Saturday | `founder_signal` | Founder/GTM/moat signal | 260 |
| Sunday | `tomorrow_in_ai` | Prediction/synthesis | 240 |

The `DayPlan` feeds into:
- the LLM system/user prompt
- the rule-based hook
- the verifier's expected taxonomy hashtags
- `content_analyst.py` perfection scoring

---

## 7. Verification — does the caption pass quality gates?

`pipeline/verify.py::verify_draft()` scores the caption 0–100 and returns `APPROVE / UNCERTAIN / REJECT`.

Checks directly on `linkedin_post`:
1. **Length:** 50–250 words
2. **AI-sounding phrases:** regex list (`in the ever-evolving landscape`, `delve`, `moreover`, etc.)
3. **Hashtag specificity:** not all generic (`#ai`, `#machinelearning`, `#technology`, etc.)
4. **Link present:** `source_url` must appear in the post
5. **No internal leak:** scoring words like `pillar_confidence` not in text
6. **Taxonomy topic:** at least one hashtag matches the day's editorial set
7. **Newsletter populated:** ≥ 80 words
8. **Title not clickbait**
9. **Claim verification:** compares draft claims to source text and checks for hallucinated numbers

Current thresholds: `APPROVE ≥ 80`, `UNCERTAIN ≥ 55`.

---

## 8. Analysis / dashboard scoring

`pipeline/content_analyst.py` computes three scores shown in the review dashboard:

- `relevance_score(item, day_plan, age)`: pillar fit + recency + source bias
- `accuracy_score(item)`: HTTP HEAD/GET health of `source_url`
- `perfection_score(draft, day_plan, use_llm=True)`: LLM-based or rule-based quality check

`proposed_action` is derived from these scores:
- `acc < 60` → `update_source`
- `rel < 60` → `skip`
- `perf < 60` → `rewrite_draft`
- no image → `replace_image`
- else → `keep`

The dashboard exposes these in the API under `draft.analysis`.

---

## 9. Publishing path

`pipeline/publishers/linkedin.py`:

```python
payload = {
    "author": author_urn,
    "lifecycleState": "PUBLISHED",
    "specificContent": {
        "com.linkedin.ugc.ShareContent": {
            "shareCommentary": {"text": draft.linkedin_post},
            "shareMediaCategory": "NONE",
        }
    },
    "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
}
```

Currently only text posts (no image upload). Image is selected for the dashboard but **not attached to the LinkedIn API payload**.

---

## 10. Known issues and gaps (as of 2026-09-01)

1. **`cmd_daily` uses the rule-based drafter.** The LLM-based `draft_item_v2()` is not the default production path.
2. **Rule-based posts are templated and repetitive.** The second paragraph is identical for every draft of the same pillar.
3. **No image in LinkedIn payload.** `shareMediaCategory` is `NONE`; images are only for human preview in the dashboard.
4. **LLM availability is fragile.** Default is local Ollama on `127.0.0.1:11434`, which is often not running.
5. **Pexels cache bug** (fixed today): `_save_pexels_cache` could `shutil.copy2` a file onto itself.
6. **Founder-signal question enforcement only in v2.** Rule-based founder posts may not end with a question.
7. **No caption A/B or variant generation.** Each draft produces exactly one `linkedin_post`.
8. **Signature phrases are defined but not injected.** `voice.signature_phrases` is unused in either drafter.
9. **Hashtags come from topics, not from the post content.** A post about MCP may get `#Reasoning` if the topic extractor mis-classified it.
10. **Newsletter section is rule-based even when caption is LLM-based.** `draft_item_v2` generates both, but `cmd_daily` bypasses v2 entirely.

---

## 11. Files that control captions

| File | Responsibility |
|---|---|
| `pipeline/drafting.py` | `Draft` model, rule-based caption generator, markdown save/load |
| `pipeline/drafting_v2.py` | LLM-based caption generator, prompt building, JSON hydration |
| `pipeline/voice.py` | Persona, tone, no-go words, CTA per post type, word caps |
| `config/calendar.py` | Day-of-week editorial plan (`DayPlan`) |
| `pipeline/llm_client.py` | Provider routing: Ollama / OpenAI / Anthropic |
| `config/settings.py` | LLM env vars and defaults |
| `pipeline/verify.py` | Quality gate scoring on the caption |
| `pipeline/content_analyst.py` | Relevance/accuracy/perfection scoring shown in dashboard |
| `pipeline/hermes.py` | `cmd_daily()` orchestration — currently picks `draft_item()` |
| `pipeline/topics.py` | Taxonomy extraction and hashtag generation |
| `pipeline/publishers/linkedin.py` | Sends `draft.linkedin_post` to LinkedIn API |

---

## 12. Where to modify for improvements

If you want to improve captions, the high-impact touch points are:

1. **Switch `cmd_daily` to `draft_item_v2()`** in `pipeline/hermes.py` (provided the LLM is reliable/cheap enough).
2. **Inject `voice.signature_phrases`** into the system prompt or post-processing.
3. **Use source-extracted key claims** more aggressively in the user prompt (already present but truncated to 800 chars).
4. **Generate 2–3 caption variants** and let the verifier/dashboard pick the best.
5. **Attach the selected image** to the LinkedIn publisher payload.
6. **Add a rewrite/Agent-edit endpoint** that edits `linkedin_post` via LLM using the same `Voice` constraints.

---

## 13. Example of the current rule-based output

From `data/queue/2026-09-01T225500Z--e82667920f5e--builder_memo.md`:

```text
Builder memo: How accurate have Ed Zitron's AI skeptic predictions been?

What changed: One comment I've seen from a lot of AI skeptics when someone responds to an AI skeptic is that all of the people who are saying that AI isn't fake are self-interested liars. Personally (to my obvious detri...

Why builders should care: this is the kind of signal that shifts how we design, deploy, and secure AI systems. Watch it, experiment with it, and share what breaks.

Read more: https://danluu.com/zitron/

#Reasoning #LlmApps #SecureAI
```

Note the generic second paragraph and the abrupt truncation of the "What changed" claim.

---

*Generated for the linkedin-pipeline repo at /opt/data/linkedin-pipeline-latest.*
