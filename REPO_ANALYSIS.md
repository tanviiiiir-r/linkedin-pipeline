# linkedin-pipeline — Full Repository Analysis

## Executive Summary

`linkedin-pipeline` is a Python CLI content machine that collects AI/security/builder signals from RSS feeds, Reddit, YouTube, Instagram, GitHub, and big-tech engineering blogs; scores them against 5 content pillars; drafts LinkedIn posts + newsletter sections; and queues them for human approval before publishing via Composio (LinkedIn/Twitter/X) or direct LinkedIn OAuth. It is designed for zero-budget, low-time operation with a focus on the "Secure AI Engineering" niche.

The repo was created on 2026-08-22 and pushed 12 commits in one day. Current state: functional end-to-end pipeline with rule-based scoring/drafting, Supabase/SQLite storage, human approval gate, and dry-run verified publishers. It is still a prototype: heavy CLI output, broad exception handling, no live posts yet, and no automated scheduling/notifications.

## Repository Metadata

| Field | Value |
|---|---|
| Repo | https://github.com/tanviiiiir-r/linkedin-pipeline |
| Description | Automated AI content collection + LinkedIn/newsletter pipeline for Secure AI Engineering niche |
| Visibility | Public |
| License | None |
| Stars/Forks/Issues | 0 / 0 / 0 |
| Language | Python (129,255 bytes) |
| Python files | 26 |
| Total Python LOC | ~3,800 |
| Functions | 185 |
| Classes | 10 |
| Tests | 5 files (12 passing when TOKEN_SECRET set) |
| External deps | 12 packages |

## Commit History

| SHA | Date | Message |
|---|---|---|
| d7c7621 | 2026-08-22 | feat: topic taxonomy, better scoring, and semantic deduplication |
| cf244d5 | 2026-08-22 | feat: add daily automated workflow command |
| d972a4f | 2026-08-22 | docs: add token and cost estimate for pipeline runs |
| a96b1da | 2026-08-22 | feat: add Google, NVIDIA, AWS, DeepMind, Cloudflare, GitHub big-tech feeds |
| 68a0dcc | 2026-08-22 | feat: add YouTube and Instagram collectors via Composio |
| 6372f1e | 2026-08-22 | feat: Reddit collector + article/newsletter compiler + improved drafts |
| d1afdd0 | 2026-08-22 | feat: add active creator feeds for Harrison Chase signal and more |
| 892abde | 2026-08-22 | feat: improve sources for Secure AI Engineering pipeline |
| 4f0b934 | 2026-08-22 | feat: Supabase PostgreSQL backend for collected items |
| 9a0e330 | 2026-08-22 | feat: Composio LinkedIn + Twitter/X publishers with dry-run safety |
| cb2d0a4 | 2026-08-22 | feat: Hermes-driven LinkedIn pipeline with MCP server, OAuth, and approval |
| 133a8ff | 2026-08-22 | Initial commit: AI content collection pipeline for Secure AI Engineering |

## Architecture

```
run.py
  └─ pipeline/hermes.py        CLI orchestrator (15 subcommands)
       ├─ collectors/          RSS, Reddit (Composio), YouTube (Composio), Instagram (Composio), GitHub
       ├─ scoring.py           Rule-based pillar + signal scoring + topic taxonomy
       ├─ topics.py            50-topic keyword taxonomy for AI Builder/Research/Security/Efficiency/Systems
       ├─ dedupe.py            URL, title, Jaccard, topic-overlap deduplication
       ├─ drafting.py          LinkedIn post + newsletter section + 3 derivative pills
       ├─ approval.py          Human-in-the-loop queue
       ├─ publishers/          Direct LinkedIn OAuth, Composio LinkedIn/Twitter
       ├─ storage.py           Pydantic Item model + SQLite fallback
       └─ storage_supabase.py  Supabase PostgreSQL JSONB backend

mcp_server.py                  MCP server exposing pipeline_status, collect_items, score_items, draft_posts, approve/publish, LinkedIn auth
config/settings.py             Environment + directory/pillar settings
```

## Data Flow

1. **Collect** — `run.py collect` fetches RSS, GitHub trending/search, Reddit/YouTube/Instagram via Composio.
2. **Dedupe** — Items compared by canonical URL, normalized title, keyword Jaccard, and topic overlap against last 500 stored items.
3. **Store** — Saved to Supabase `pipeline_items` table (JSONB) or local SQLite; mirrored as markdown in `data/raw/`.
4. **Score** — `score_item()` assigns pillar + confidence + signal strength; filters noise (rants, unsupported claims).
5. **Draft** — `draft_item()` produces LinkedIn post, newsletter section, short/forward/narrative pills.
6. **Queue** — Drafts saved to `data/queue/` as markdown with frontmatter.
7. **Approve** — `run.py approve <id>` marks item ready to publish.
8. **Publish** — `run.py publish --target linkedin|twitter` uses Composio (dry-run verified) or direct LinkedIn OAuth.

## Sources (37 total)

| Type | Count | Examples |
|---|---|---|
| RSS feeds | 28 | Hacker News, Chip Huyen, Eugene Yan, Simon Willison, Latent Space, TechCrunch AI, The Rundown AI, Dark Reading, BleepingComputer, PortSwigger, arXiv, LangChain, Interconnects, Google Cloud/Developers, NVIDIA, AWS, Cloudflare, GitHub, DeepMind, Pinterest |
| GitHub trending | 3 | Python, TypeScript, Go |
| GitHub search | 2 | ai+agent, llm+security |
| Reddit communities | 14 | LocalLLaMA, MachineLearning, ai_agents, LangChain, netsec, cybersecurity, etc. |
| YouTube channels | 4 | Andrej Karpathy, AI Explained, Two Minute Papers, Yannic Kilcher |
| Instagram | 1 | connected own account only |

## Content Pillars

| Pillar | Purpose |
|---|---|
| Tool Drop | New AI tool/API/model with one-line use case |
| Viral Explained | Break down trending demo/launch/repo |
| Pattern Spotting | Connect 2–3 signals into emerging workflow |
| Builder Memo | Workflow, prompt pattern, cost/perf trick |
| Tomorrow in AI | Prediction or question sparked by news |

## Topic Taxonomy (50 topics, 5 categories)

- **AI Builder**: ai-agents, llm-apps, rag, mcp, tool-use, agent-memory, agent-orchestration, coding-agents, ai-devtools, open-source-ai
- **AI Research**: new-model, reasoning, multimodal, reinforcement-learning, post-training, synthetic-data, evaluation, model-architecture, ai-science
- **AI Security**: prompt-injection, indirect-prompt-injection, agent-security, model-security, data-exfiltration, tool-security, identity-access, sandboxing, ai-red-teaming, model-evaluation, supply-chain-security
- **AI Efficiency**: inference, quantization, distillation, caching, speculative-decoding, latency, gpu, accelerators, model-routing, cost-optimization
- **AI Systems**: ai-infrastructure, observability, deployment, mlops, llmops, distributed-systems, databases, vector-databases, cloud, reliability

## CLI Commands

```bash
python run.py collect [--dry-run] [--limit N] [--skip-reddit|--skip-youtube|--skip-instagram]
python run.py reddit|youtube|instagram --limit N
python run.py daily --collect-limit N --draft-limit N --newsletter-limit N
python run.py score --limit N --min-confidence X --min-signal Y
python run.py draft --limit N
python run.py newsletter --limit N --title "..."
python run.py queue
python run.py approve <item_id>
python run.py publish --target linkedin|twitter [--dry-run] [--limit N]
python run.py linkedin_auth_url|linkedin_exchange|linkedin_status|linkedin_logout
```

## Strengths

1. **Zero-budget design** — uses free RSS, Composio free tier, Supabase free tier, no paid APIs.
2. **Rule-based, no LLM cost** — current pipeline costs $0 in tokens per run.
3. **Good source breadth** — covers creators, news, research, security, big-tech engineering, GitHub, Reddit, YouTube.
4. **Human approval gate** — publishing requires explicit approval by default.
5. **Multiple publisher backends** — Composio and direct OAuth, both with dry-run safety.
6. **Supabase + SQLite dual storage** — cloud primary with local fallback.
7. **Taxonomy-driven topics** — replaces generic `#AI` hashtags with specific technical tags.
8. **MCP server included** — pipeline can be driven by Hermes/Claude Code/Cursor via MCP.
9. **Fast iteration** — 12 commits in one day shows active development.

## Weaknesses / Risks

1. **No tests for new modules** — `topics.py`, `dedupe.py`, `collectors/reddit.py`, `collectors/youtube.py`, `collectors/instagram.py` lack dedicated tests.
2. **Broad exception handling** — 15+ `except Exception` blocks swallow errors silently.
3. **Heavy CLI output** — `hermes.py` has 74 print statements; noisy logs.
4. **No live post validation** — publishers tested only in dry-run.
5. **No cron/scheduling** — `daily` command exists but not scheduled.
6. **No notifications** — run summaries only written to stdout and local log file.
7. **Instagram collector is passive** — only fetches connected account's own media, no external creator feeds.
8. **Draft quality still template-heavy** — reads AI-generated despite improvements; needs LLM humanizer.
9. **Scoring still keyword-based** — can miss nuanced builder/security relevance.
10. **No monitoring/alerting** — if a collector fails, the daily run may silently produce zero items.
11. **Source drift** — feeds like Karpathy, Reuters, The Batch were already found broken; needs periodic health checks.
12. **License missing** — no open-source license attached.

## Token/Cost Estimate (from TOKEN_ESTIMATE.md)

- Current pipeline: **0 LLM tokens per run**.
- Collected volume: 194 items, ~135k tokens of content.
- With LLM topic extraction + 5 drafts/day: ~$1.64/month on GPT-4o-mini, ~$0.16/month on Kimi/GLM.

## Security Observations

- Credentials live in `.env` only (gitignored).
- `.env.example` documents required keys but `.env` itself not in repo.
- Supabase service role key, LinkedIn client secret, GitHub token, Composio API key handled via env.
- Token encryption uses `TOKEN_SECRET` via Fernet (optional but recommended).
- No secrets printed to logs or hardcoded in source.

## Recommendations

### Must do before daily automation
1. Add Telegram/Discord notification for daily summary.
2. Schedule `run.py daily` via cron or Hermes cronjob.
3. Add health-check logging so empty runs are flagged.
4. Verify at least one real LinkedIn/Twitter dry-run publish with your credentials.

### Quality improvements
5. Add tests for `topics.py`, `dedupe.py`, and social collectors.
6. Replace broad `except Exception` with specific exceptions + retry/backoff.
7. Add LLM humanizer step for drafts (cheap on Kimi/GLM).
8. Implement source feed health monitoring and auto-disable broken feeds.
9. Add a license (MIT recommended for open tooling).

### Scale improvements
10. Add semantic embeddings for deduplication (e.g. sentence-transformers or Jina embeddings, free local option).
11. Add engagement weighting (HN points, Reddit score, GitHub stars) into scoring.
12. Add newsletter compilation directly from queued drafts and email/Substack publishing path.

## Verdict

The repo is a **solid, working prototype** for an automated AI-builder content pipeline. It already does collection, scoring, drafting, approval, and dry-run publishing across 37 sources. The main gap is operationalizing it: scheduling, notifications, health checks, and one live publish sanity check. With those, it can run daily with near-zero cost and minimal manual intervention.
