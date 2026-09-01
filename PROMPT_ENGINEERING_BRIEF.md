# LinkedIn Pipeline — Image Generation Technical Brief

## Project Goal
Generate high-quality LinkedIn cover-image candidates for daily AI/tech posts with **zero cost** where possible, while keeping source labels honest and the operator able to preview/select the best image.

## Candidate Policy
Each draft must expose **exactly 4 image options** in the review dashboard:

1. **2 non-AI candidates**
   - Source article OpenGraph image (`og:image`).
   - Source article Twitter card image (`twitter:image`).
   - Real stock photo from **Pexels** (API key required).
   - If non-AI sources are short, the remaining slot is filled with an **extra AI angle** so the dashboard still shows 4 options, but it must be labeled as AI (not stock).

2. **2 AI-generated candidates**
   - Generated from two different angles chosen deterministically per draft:
     - `environment` — wide establishing shot / workspace / lab.
     - `message` — conceptual editorial still-life / symbolic object.
     - `focus` — macro detail / product-photography.
     - `pov` — first-person over-the-shoulder builder view.
   - Angles are rotated so different drafts get different pairs.

## Image Pipeline Entry Points

### `pipeline/image_engine.py`
Primary module. Key functions:

- `candidates_for_post(...)` — returns `(active_image_path, candidate_paths, source_label)`.
- `image_for_post(...)` — legacy single-image entry point; now delegates to `candidates_for_post`.
- `prompt_for_post(day, pillar, title, linkedin_post, hashtags, angle, stock_style, source_url)` — builds the final prompt.
- `_extract_visual_keywords(...)` — extracts subject + keyword list from title/post/hashtags/source URL.
- `_visual_anchor(...)` — picks a concrete visual anchor tied to the post topic.
- `_build_visual_scene(...)` — composes scene description for each angle.
- `_build_style(...)` — composes the style/mood string per pillar.

### `pipeline/review_server.py`
HTTP API for the review dashboard:

- `GET /api/drafts?status=pending|approved|rejected` — lists drafts.
- `POST /api/select-image` — chooses a candidate as the active image.
- `POST /api/regenerate-image` — regenerates images for a draft.

### `pipeline/review_dashboard.py`
Static dashboard generator. It copies active + candidate images into `data/review/images/` and renders a JavaScript UI embedded as a string.

## Current Prompt Structure

```
Professional LinkedIn cover image (1.91:1 landscape) about {subject}.
Core topic: {keywords}.
Scene direction: {scene}
Visual style: {style}.
High detail, sharp focus, cinematic lighting, clean centered composition,
visually striking, suitable for a professional business and developer audience.
No text, letters, numbers, words, logos, watermarks, trademarks, UI chrome,
or readable labels. No people unless explicitly requested by the scene direction.
```

### Current Issues
- Repetitive clauses (“High detail, sharp focus, cinematic lighting” appears twice).
- Generic or abstract anchors such as “luminous chain-of-thought diagram” can confuse cheap models.
- The `viral_explained` pillar style is generic tech editorial; a test expects “bold” or “news-style”.
- Named-entity extraction is weak, so prompts often miss the actual product/model in the title.
- Pollinations (free) is default, but prompt adherence is mediocre.

## Providers & Cost Trade-offs

| Provider | Model | Cost | Speed | Quality | Notes |
|---|---|---|---|---|---|
| **Pollinations** | `flux` / `flux-realism` | Free | Medium | Okay | Rate-limited, no API key. Good for zero-cost testing. |
| **FAL** | `fal-ai/flux/schnell` | ~$0.003/image | Fast | Medium | Cheapest paid option. |
| **FAL** | `fal-ai/flux/dev` | ~$0.02–0.03/image | Medium | High | Better prompt adherence than schnell. |
| **FAL** | `fal-ai/flux-pro/v1.1` | ~$0.03–0.04/image | Medium | Higher | Production-quality images. |
| **FAL** | `fal-ai/flux-pro/v1.1-ultra` | ~$0.05–0.07/image | Medium | Highest | Best for final picks. |
| **FAL** | `fal-ai/ideogram/v2` | ~$0.05–0.08/image | Medium | Very high | Excellent at obeying “no text.” |
| **FAL** | `fal-ai/recraft-v3` | ~$0.04–0.06/image | Medium | Very high | Strong vector + photorealism. |

## Constraints
- **Budget priority**: zero dollars spent. Pollinations must remain the default.
- **Honest labels**: AI-generated fallbacks must never be labeled as “stock.”
- **No text**: every prompt must end with a strong “no text, logos, UI, labels” clause.
- **Aspect ratio**: LinkedIn feed = ~1.91:1 landscape (1200×627 target).
- **Usability**: each image must be ≥400×200 px; smaller images are discarded.

## Desired Improvements
1. Simplify and de-duplicate the prompt template.
2. Improve keyword extraction so prompts reference real products/models/companies from the title.
3. Make anchors more concrete and less abstract for cheap models.
4. Add pillar-specific style cues, including “bold / news-style” for `viral_explained`.
5. Keep candidate policy: 2 non-AI + 2 AI, 4 total.
6. Optionally improve source order: OG → Twitter → Pexels → AI angles.

## Output Files
- Active image: `data/images/{slug}.png`
- Candidate images: `data/image_candidates/{item_id}/`
- Review dashboard: `data/review/index.html` + `data/review/assets/`

## Environment Variables
- `IMAGE_PROVIDER` — `pollinations` (default), `fal`.
- `FAL_KEY` — required for FAL.
- `FAL_MODEL` — currently `fal-ai/flux/schnell`; user wants to switch to a better FAL model.
- `PEXELS_API_KEY` — required for real stock photos.

## Next Steps
1. Rewrite `prompt_for_post`, `_extract_visual_keywords`, `_visual_anchor`, `_build_visual_scene`, and `_build_style` based on this brief.
2. Fix the failing test `test_prompt_for_post_matches_day_style`.
3. Run tests and deploy to `review.caraxis.online`.
