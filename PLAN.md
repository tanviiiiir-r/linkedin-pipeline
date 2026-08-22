# AI Builder Content Machine — Zero-Cost Plan

**Goal:** Post high-quality, value-first AI updates for AI builders, sourced from already-viral/trendy content. Also start a newsletter.

**Principles:** Quality > quantity. Curation > creation. Zero paid tools.

---

## 1. Content Pillars

Pick 3–5 repeatable angles so every post has a clear job:

| Pillar | What it covers | Why it works |
|--------|----------------|--------------|
| **Tool Drop** | New AI tool, model, or API with a one-line use case | Builders want tactical edges |
| **Viral Explained** | Break down a trending AI demo, launch, or GitHub repo | Rides existing attention |
| **Pattern Spotting** | Connect 2–3 signals into an emerging AI workflow | Positions you as a curator |
| **Builder Memo** | Share a workflow, prompt pattern, or cost/perf trick from the community | Value-first, no fluff |
| **Tomorrow in AI** | One prediction or question sparked by the week’s news | Thought leadership |

---

## 2. Source System (free)

Use RSS feeds + manual curation. Bot-gated sites (OpenAI, Anthropic, LinkedIn, Twitter) are unreliable from a VPS, so prioritize open feeds.

### Tier 1 — reliable open RSS feeds
- Hacker News (`https://news.ycombinator.com/rss`)
- arXiv AI papers (`https://export.arxiv.org/rss/cs.AI`)
- Lilian Weng blog (`https://lilianweng.github.io/feed.xml`)
- Andrej Karpathy blog (`https://karpathy.ai/blog/feed.xml`)
- Simon Willison (`https://simonwillison.net/atom.xml`)
- The Decoder (`https://the-decoder.com/feed/`)
- Indie Hackers (`https://www.indiehackers.com/feed`)
- Product Hunt AI feed (`https://www.producthunt.com/feed?t=ai`)

### Tier 2 — read directly via browser/reader when needed
- LinkedIn top AI voices (copy URLs manually)
- Twitter/X via Nitter instances (unstable)
- Reddit r/LocalLLaMA, r/MachineLearning (use .rss or browse)
- GitHub Trending (`https://github.com/trending?since=daily`)

### Tier 3 — newsletters to learn from
- The Batch (Deeplearning.AI)
- Import AI
- TLDR AI
- AlphaSignal
- Latent Space

---

## 3. Curation Workflow

Daily (15–20 min):
1. **Scan** — run `blogwatcher-cli scan` on source feeds.
2. **Score** — pick 1–3 items that match a pillar and have strong signals:
   - HN points > 100
   - GitHub stars trending
   - Multiple sources talking about the same thing
   - A clear “so what?” for builders
3. **Extract** — open the top item, grab the core insight, link, and one quote.
4. **Draft** — write a 100–200 word LinkedIn post + a 300–500 word newsletter section.
5. **Humanize** — run through humanizer skill so it doesn’t sound AI-generated.

Weekly (30 min):
- Compile 3–5 daily picks into a newsletter issue.
- Add one original take or prediction.
- Publish via free newsletter platform (Substack, Beehiiv, Buttondown).

---

## 4. Content Formats

### LinkedIn post template
```
{Hook — one line, contrarian or curiosity}

{What happened — 1 sentence}
{Why it matters for AI builders — 2–3 sentences}
{Actionable takeaway or prediction — 1 sentence}

{Link}

#{tag} #{tag} #{tag}
```

### Newsletter section template
```
## 1. {Title}
**Source:** {URL}
**Signal:** {why it’s trending}
**Builder takeaway:** {what to do with it}
**Quote:** “...”
```

---

## 5. Hermes Automation Layer

Skills to use:
- `blogwatcher` — RSS scanning
- `defuddle` — extract clean article text
- `agent-reach` — internet search / social monitoring (when configured)
- `humanizer` — polish AI-generated copy
- `social` (marketingskills) — content templates and calendars
- `linkedin-automation` — publish posts (tomorrow)
- `xurl` — cross-post to X/Twitter if needed

Proposed cron job:
- **Daily 9 AM UTC:** scan feeds, score items, draft 1 LinkedIn post + newsletter snippet
- **Weekly Friday 10 AM UTC:** compile newsletter, queue for review
- Optional: **approval gate** before publishing anything with side effects

---

## 6. LinkedIn + Newsletter Posting (next steps)

Tomorrow:
1. Choose LinkedIn auth path:
   - **Composio official API** (safer, OAuth)
   - **Browser cookie fallback** (riskier, personal profile only)
2. Connect one account and run a dry-run post.
3. Pick a newsletter host:
   - **Substack** (free, easiest)
   - **Beehiiv** (free tier, growth tools)
   - **Buttondown** (free up to 1k subs)
4. Set up the first issue template.

---

## 7. Quality Checks (no exceptions)

Before any post goes live:
- [ ] Is this useful to an AI builder?
- [ ] Is the source real and verifiable?
- [ ] Is the take original or properly credited?
- [ ] Does it pass the humanizer sniff test?
- [ ] Is there a clear CTA or question?

---

## 8. Metrics to Track (free)

| Metric | Tool |
|--------|------|
| LinkedIn impressions/engagement | LinkedIn native analytics |
| Newsletter opens/clicks | Substack/Beehiiv built-in |
| Feed freshness | `blogwatcher-cli articles` |
| Viral source score | Manual HN points / GitHub stars / Reddit upvotes |

---

**Next action:** decide the newsletter host and LinkedIn auth path, then I’ll wire the first automated run.
