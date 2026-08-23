# PROJECT-BRIEF — linkedin-pipeline

> One-page project identity. Fill this before anything else. Everything downstream routes from here.

## 1. What are we building?

A Hermes-driven LinkedIn content automation pipeline for the "Secure AI Engineering" niche.
It collects signals from RSS feeds, GitHub, Reddit, YouTube, Instagram, and big-tech engineering blogs;
scores them against five content pillars; drafts LinkedIn posts + newsletter snippets;
queues them for human approval; and publishes via direct LinkedIn OAuth v2 or dry-run fallback.

## 2. Inputs → Outputs

- **Inputs:** RSS/Atom feeds, GitHub trending/search, Reddit posts, YouTube videos, Instagram media, big-tech blogs, manual YouTube URLs.
- **Outputs:** Scored content items, LinkedIn post drafts, newsletter sections, published LinkedIn posts, daily checkpoint logs.

## 3. Autonomy & trust

- **Autonomy level:** bounded (agent can collect, score, and draft; publishing requires explicit human approval)
- **Human-in-the-loop points:** draft approval before any publish; LinkedIn OAuth authorization by operator
- **Failure tolerance:** publish failures must be visible and recoverable; collection failures must not crash the daily run
- **Trust boundary:** agent cannot post content or store LinkedIn tokens without operator action

## 4. Why this matters

The operator wants a zero-cost, value-first content machine that rides existing attention in AI/security/builder spaces while staying human-curated. The pipeline keeps the operator's voice and judgment in the loop, avoiding fully automated spam.

## 5. Anti-goals (out of scope)

- Fully automated, unapproved publishing.
- Scraping bot-gated sites (OpenAI, Anthropic, X/Twitter) or bypassing rate limits.
- Building a generic social media scheduler; this is niche-curated content only.

## 6. Quality stance

This project runs under the GSD Loop Protocol: plan → build with gates → verify by a separate context/model → ship.
Quality is not a phase; it is the harness the loop runs in.
