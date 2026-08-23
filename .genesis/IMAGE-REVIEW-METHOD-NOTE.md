# Image Review Method Note

**Date:** 2026-08-23

## What I actually analyzed

The review in `.genesis/IMAGE-REVIEW-AND-IMPROVEMENTS.md` was based on:

1. **The 8 generated PNG files** in `.genesis/examples/images/`:
   - `ai_security_red_team_visual.png`
   - `cloud_ciso_perspectives_sticking_to_security_fundamentals_in.png`
   - `glm_5_3_how_chinese_labs_keep_stride_with_the_frontier.png`
   - `govern_ai_agent_tool_access_with_amazon_bedrock_agentcore_ga.png`
   - `how_agents_can_delegate_better.png`
   - `introducing_gemini_3_7_flash.png`
   - `secure_all_your_internal_vibe_coded_applications_in_one_clic.png`
   - `teaching_everyone_to_fish_for_tokens.png`

2. **The generation metadata** in `.genesis/examples/7-day-generated-images.md`:
   - Prompts
   - Source URLs
   - Flux workflow (flux1-dev.sft)
   - Output dimensions (1024×1024)

3. **General LinkedIn creative best-practice patterns** I have in training:
   - Feed-optimized aspect ratios (1.91:1 landscape, 4:5 vertical, 1:1 square)
   - B2B LinkedIn image conventions by content genre (tool launch, explainer, pattern, memo, security, founder, thought leadership)
   - Common failure modes of text-to-image models (fake text, fake UI, hallucinated logos, generic stock look)

## What I did NOT analyze

- No actual engagement data from your LinkedIn account.
- No A/B test results.
- No scrape or export of top-performing posts from your niche.
- No competitor post dataset.

## Why the phrasing "top-performing posts" was misleading

In the review I wrote:

> "Genre-by-genre review vs. top-performing LinkedIn posts"

That was imprecise. A more accurate heading would be:

> "Genre-by-genre review vs. common LinkedIn creative patterns for each content genre"

The recommendations come from:
- Platform-format knowledge (aspect ratios, safe zones, no-text rules)
- Genre conventions (what a security post vs. a founder post usually looks like)
- Image-generation failure patterns (what Flux/SD tends to get wrong)

## What would make the review stronger

To replace inference with evidence, we would need one of:

1. **Operator's own LinkedIn analytics export** — top 20 posts by impressions/engagement with images.
2. **Manual benchmark collection** — save 10–20 high-performing posts per genre from feeds you trust (e.g. Interconnects, Import AI, Latent Space, Anthropic/Google Cloud engineers).
3. **A/B test dataset** — publish 2 image variants and measure impressions/reactions/comments.
4. **Human rater survey** — show the 8 images to 5–10 target readers and score scroll-stop, relevance, professionalism.

## Suggested correction

I should update `.genesis/IMAGE-REVIEW-AND-IMPROVEMENTS.md` section 3 heading from:

> "Genre-by-genre review vs. top-performing LinkedIn posts"

to:

> "Genre-by-genre review vs. LinkedIn creative conventions for each content genre"

And add a note at the top:

> "This review is based on platform creative conventions and image-generation failure modes, not on actual engagement data from the operator's account or competitors."
