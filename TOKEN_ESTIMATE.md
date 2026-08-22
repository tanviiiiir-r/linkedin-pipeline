# Token / Cost Estimate for Content Pipeline

## Current pipeline (rule-based)

Stage | Token cost | Notes
---|---|---
Collection (RSS/Reddit/YouTube/Instagram/GitHub) | 0 | HTTP + Composio tool calls
Storage / dedupe (Supabase/SQLite) | 0 | Database operations
Scoring (regex/keywords) | 0 | No LLM
Drafting (templates) | 0 | No LLM
Publishing (Composio LinkedIn/Twitter) | 0 | Tool execution only
**Total current LLM tokens per run** | **0** | Free if you do not add LLM enrichment

## Collected content volume (measured from current DB)

- **194 items** currently stored
- **540,785 chars** total raw+summary+title text
- ~**135,196 tokens** of collected content (chars / 4)
- Per-source breakdown:
  - RSS: 120 items, ~123,342 tokens
  - Reddit: 42 items, ~8,088 tokens
  - YouTube: 4 items, ~2,358 tokens
  - GitHub search: 13 items, ~1,126 tokens
  - GitHub trending: 15 items, ~280 tokens

With `--limit 5` per source, a full run collects roughly **250 items** and ingests about **~175,000 tokens** of content into storage.

## If we add LLM topic extraction

Assumption: 600 input tokens per item + 200 output tokens.

- Per item: ~800 tokens
- Per run (250 items): ~200,000 tokens
- Cost with GPT-4o-mini: ~**$0.052 / run**
- Monthly (daily): ~**$1.57 / month**

## If we add LLM drafting for 5 worthy items

Assumption: 800 input tokens per draft + 500 output tokens.

- Per draft: ~1,300 tokens
- Per run (5 items): ~6,500 tokens
- Cost with GPT-4o-mini: ~**$0.002 / run**
- Monthly (daily): ~**$0.06 / month**

## Combined LLM cost (topic extraction + drafting)

- Per run: ~**$0.054**
- Monthly (daily): ~**$1.64**
- With Kimi K2.7 / GLM 5.2 (roughly 10x cheaper): ~**$0.16 / month**

## Composio / API call volume per run

- RSS feed fetches: ~28
- Reddit tool calls: ~14
- YouTube tool calls: ~8 (channel id + videos)
- Instagram tool calls: ~2
- Publish calls: 1-2 per approved item

Composio's free tier covers these volumes; no extra token cost.

## Key takeaway

The pipeline as it stands today is **zero LLM-token cost**. Adding lightweight LLM enrichment (topic extraction + 5 drafts per run) is cheap even on GPT-4o-mini (~$1.64/month) and essentially free on Kimi/GLM (~$0.16/month).
