# Creator Post Pattern Analysis

Small sample (n=10) of recent posts from AI/builder voices, collected via web search + fetch.

| Creator/Title | Image? | Words | Lines | Emojis | Format | Hook |
|---|---|---|---|---|---|---|
| [swyx — 📣 swyx, Curator at AI Engineer & La...](https://www.linkedin.com/posts/workos-inc_swyx-curator-at-ai-engineer-latent-activity-7491161244771475458-3Rdv) | no | 154 | 5 | 2 | emoji-light, link-share | # 📣 swyx, Curator at AI Engineer & Latent Space | AI Engineering News, Essays and Interviews, at Agent Night. | WorkOS · |
| [swyx — swyx ​ on LinkedIn...](https://www.linkedin.com/posts/shawnswyxwang_the-big-show-begins-tonight-activity-7477033229024366592-EzyK) | no | 201 | 15 | 2 | bullet-list, emoji-light, link-share | the big show begins tonight | swyx | 12 comments |
| [Lenny Rachitsky — 💥 Announcing Lenny’s Job...](https://www.linkedin.com/posts/lennyrachitsky_announcing-lennys-jobs-the-best-place-activity-7495536257188519936-zT2o) | yes | 212 | 7 | 2 | emoji-light | 💥 Announcing Lenny’s Jobs: The best place in the world to find, vet, and land your dream job I’ve spent thousands of hou |
| [Lenny Rachitsky — Designers are the unhapp...](https://www.linkedin.com/posts/lennyrachitsky_designers-are-the-unhappiest-people-in-tech-activity-7494882992117428224-zcxZ) | no | 172 | 14 | 6 | emoji-heavy, link-share | # Designers are the unhappiest people in tech. | Lenny Rachitsky · LinkedIn · 2026-08-16 |
| [Chip Huyen — Chip Huyen is a P99 CONF favo...](https://www.linkedin.com/posts/scylladb_scylladb-p99conf-activity-7494441532826112001-J8KK) | yes | 176 | 6 | 0 | link-share | # Chip Huyen is a P99 CONF favorite, and for good reason! In our free, virtual, and highly technical October 21-22 event |
| [Chip Huyen — Chip Huyen on LinkedIn...](https://www.linkedin.com/posts/chiphuyen_aiengineering-aicoding-activity-7468735519141609472-LT0w) | no | 196 | 14 | 0 | link-share | #aiengineering #aicoding | Chip Huyen | 45 comments |
| [Eugene Yan — When evaling models, we ancho...](https://www.linkedin.com/posts/eugeneyan_when-evaling-models-we-anchor-on-the-median-activity-7485510185558372353-gqs8) | yes | 193 | 6 | 0 | short-text | # When evaling models, we anchor on the median task. But this is like how devs estimate the median task accurately but u |
| [Eugene Yan — Using LLMs to secure source c...](https://www.linkedin.com/posts/eugeneyan_using-llms-to-secure-source-code-claude-activity-7467770404699283456-aVKh) | yes | 162 | 23 | 0 | bullet-list, link-share | Using LLMs to secure source code | Claude by Anthropic | Eugene Yan | 15 comments |
| [Simon Willison — Simon Willison: “So that'...](https://www.linkedin.com/posts/dwellington_an-ai-model-from-meta-also-hacked-another-activity-7491055219007598594-UuYx) | no | 96 | 4 | 0 | link-share | # Simon Willison: “So that's Anthropic, OpenAI, and Meta. Google really needs to catch up on accidentally cyberattacking |
| [Simon Willison — 2025: The year in LLMs | ...](https://www.linkedin.com/posts/simonwillison_2025-the-year-in-llms-activity-7412323835556900864-Pe-M) | yes | 176 | 11 | 0 | link-share | 2025: The year in LLMs | Simon Willison | 26 comments |

## What the samples mean for ComfyUI prompts

### Format distribution
- **link-share**: 8 posts
- **emoji-light**: 3 posts
- **bullet-list**: 2 posts
- **emoji-heavy**: 1 posts
- **short-text**: 1 posts

### Image usage
- Posts with a custom/image preview card: **5/10 (50%)**
- These landscape preview cards are typically article-cover style, not photographic scenes.

### Text-pattern observations
- **Hooks are short, concrete, and often controversial or newsy** ('Announcing...', 'Designers are the unhappiest...', 'the big show begins tonight').
- **Bullet pacing is common** for multi-point explainers; emoji checkmarks replace custom graphics for quick visual rhythm.
- **Link-shares dominate**; the visual is usually the OpenGraph/article preview rather than a custom generated image.
- **When no image is present**, the first line must carry all the scroll-stopping power.

### ComfyUI prompt recommendations by day type
| Day type | Current approach | What samples suggest |
|---|---|---|
| tool_drop | Abstract SaaS UI screenshot | **Use a single hero product card with icon + tool name area**, not a full dashboard. Keep it readable-as-shape. |
| viral_explained | Bold editorial illustration | **News-style header with one strong visual metaphor** works better than generic 'dramatic tech'. |
| pattern_spotting | Network diagram | Samples use bullets, not images. If image, show **two connected panels/inputs→output**. |
| builder_memo | Developer workspace | Good direction; add **one focused UI element (terminal snippet, config panel)** and keep warm lighting. |
| security_signal | Cyber visual | Link-share article covers dominate. Use **dark editorial header with one threat metaphor** (lock, shadow figure, CVE badge). |
| founder_signal | Founder at laptop | Samples are text/link heavy. If image, **strategic office scene or one clean market-timing chart**. |
| tomorrow_in_ai | Futuristic horizon | Samples are annual recap/link share. Use **wide horizon with one central symbol** (trend arrow, timeline, city silhouette). |
