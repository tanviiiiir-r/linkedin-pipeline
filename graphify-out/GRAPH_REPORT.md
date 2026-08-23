# Graph Report - linkedin-pipeline  (2026-08-23)

## Corpus Check
- 32 files · ~22,054 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 369 nodes · 864 edges · 17 communities detected
- Extraction: 59% EXTRACTED · 41% INFERRED · 0% AMBIGUOUS · INFERRED: 357 edges (avg confidence: 0.65)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]

## God Nodes (most connected - your core abstractions)
1. `Draft` - 71 edges
2. `Item` - 70 edges
3. `DirectLinkedInPublisher` - 35 edges
4. `cmd_daily()` - 21 edges
5. `save_item()` - 20 edges
6. `ScoreResult` - 19 edges
7. `score_item()` - 18 edges
8. `init_db()` - 17 edges
9. `draft_item()` - 14 edges
10. `ComposioLinkedInPublisher` - 14 edges

## Surprising Connections (you probably didn't know these)
- `collect_items()` --calls--> `cmd_collect()`  [INFERRED]
  mcp_server.py → pipeline/hermes.py
- `list_collected_items()` --calls--> `init_db()`  [INFERRED]
  mcp_server.py → scripts/collect.py
- `list_collected_items()` --calls--> `list_items()`  [INFERRED]
  mcp_server.py → pipeline/storage.py
- `score_items()` --calls--> `cmd_score()`  [INFERRED]
  mcp_server.py → pipeline/hermes.py
- `list_worthy_items()` --calls--> `init_db()`  [INFERRED]
  mcp_server.py → scripts/collect.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.06
Nodes (45): cmd_linkedin_auth_url(), cmd_linkedin_exchange(), authorization_url(), DirectLinkedInPublisher, DryRunPublisher, exchange_code(), get_publisher(), LinkedIn publishing adapters: direct OAuth v2 (free personal API) + safe dry-run (+37 more)

### Community 1 - "Community 1"
Cohesion: 0.09
Nodes (46): _clean_text(), compile_newsletter(), draft_item(), _extract_claims(), _hashtags_for(), load_drafts(), _parse_draft_markdown(), Generate LinkedIn post + newsletter snippet from a scored item.  This module rep (+38 more)

### Community 2 - "Community 2"
Cohesion: 0.08
Nodes (37): BaseModel, _composio_bin(), ComposioLinkedInPublisher, ComposioTwitterPublisher, get_composio_linkedin_publisher(), get_composio_twitter_publisher(), Composio-based publishers for LinkedIn and Twitter/X.  These call the Composio C, Publish approved drafts to Twitter/X via Composio's connected account. (+29 more)

### Community 3 - "Community 3"
Cohesion: 0.09
Nodes (40): collect_github_search(), collect_github_trending(), collect_rss(), estimate_tokens(), extract_claims(), extract_with_jina(), fetch_feed(), init_db() (+32 more)

### Community 4 - "Community 4"
Cohesion: 0.16
Nodes (20): _date_str(), ensure_checkpoint_dir(), list_checkpoints(), _now(), Daily checkpoint logging for the content pipeline.  Writes a structured CURRENT., Write today's checkpoint and update CURRENT.md., Return the current checkpoint content if it exists., Return recent checkpoint files. (+12 more)

### Community 5 - "Community 5"
Cohesion: 0.18
Nodes (18): cmd_newsletter(), cmd_publish(), cmd_score(), ensure_dirs(), Centralized, environment-aware settings., _connection(), init_db(), item_exists() (+10 more)

### Community 6 - "Community 6"
Cohesion: 0.14
Nodes (11): get_storage(), _item_to_row(), _markdown_mirror(), Supabase PostgreSQL storage backend for collected items.  Mirrors the interface, Return a SupabaseStorage if configured, otherwise None (caller falls back to SQL, PostgreSQL-backed item store with optional local markdown mirror., Ensure the items table exists., _slugify() (+3 more)

### Community 7 - "Community 7"
Cohesion: 0.12
Nodes (19): approve_draft(), list_pending(), list_ready_to_publish(), mark_published(), Human-in-the-loop approval queue., Return drafts awaiting human approval., Return drafts approved but not yet published., Atomically update a boolean frontmatter key for the draft matching item_id. (+11 more)

### Community 8 - "Community 8"
Cohesion: 0.18
Nodes (17): canonical_url(), content_similarity(), find_duplicate(), is_duplicate(), jaccard_similarity(), _keyword_set(), normalize_title(), Deduplication helpers for collected items.  Layered strategy: 1. Canonical URL n (+9 more)

### Community 9 - "Community 9"
Cohesion: 0.18
Nodes (15): _anthropic_complete(), complete(), draft_from_summary(), is_available(), LLMResponse, _ollama_complete(), _openai_complete(), Provider-agnostic LLM client.  Defaults to a local Ollama endpoint (OpenAI-compa (+7 more)

### Community 10 - "Community 10"
Cohesion: 0.39
Nodes (8): collect_youtube(), _get_channel_id(), _normalize_channel(), _parse_iso8601(), YouTube collector using Composio's connected YouTube app.  Collects recent video, Convert YouTube publishedAt to ISO datetime string., _run(), _video_url()

### Community 11 - "Community 11"
Cohesion: 0.28
Nodes (8): extract_topics(), hashtags_from_topics(), _preprocess(), primary_topic(), Topic extraction and taxonomy tagging for pipeline items.  Uses a keyword-driven, Return top matching topics from the taxonomy for the given text., Convert topics into a compact, non-generic hashtag set., _build_draft_from_llm()

### Community 12 - "Community 12"
Cohesion: 0.39
Nodes (8): collect_reddit(), _composio_bin(), _execute(), fetch_subreddit(), _post_to_item(), Reddit collector using Composio's connected Reddit app.  Collects top/hot posts, Collect top posts from configured subreddits., _utc_from_timestamp()

### Community 13 - "Community 13"
Cohesion: 0.38
Nodes (6): Tests for youtube_draft helpers., test_item_from_youtube_url_creates_item(), test_video_id_invalid(), test_video_id_short(), test_video_id_standard_url(), _video_id()

### Community 14 - "Community 14"
Cohesion: 0.67
Nodes (1): Entry point for the MCP server.  Usage:     python run_mcp.py [--host HOST] [--p

### Community 15 - "Community 15"
Cohesion: 1.0
Nodes (1): Hermes-driven LinkedIn content pipeline.

### Community 16 - "Community 16"
Cohesion: 1.0
Nodes (1): Central test environment setup.  Each test module currently mutates os.environ.

## Knowledge Gaps
- **23 isolated node(s):** `Entry point for the MCP server.  Usage:     python run_mcp.py [--host HOST] [--p`, `Supabase PostgreSQL storage backend for collected items.  Mirrors the interface`, `PostgreSQL-backed item store with optional local markdown mirror.`, `Ensure the items table exists.`, `Return a SupabaseStorage if configured, otherwise None (caller falls back to SQL` (+18 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 14`** (3 nodes): `main()`, `run_mcp.py`, `Entry point for the MCP server.  Usage:     python run_mcp.py [--host HOST] [--p`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 15`** (2 nodes): `Hermes-driven LinkedIn content pipeline.`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 16`** (2 nodes): `Central test environment setup.  Each test module currently mutates os.environ.`, `conftest.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Item` connect `Community 1` to `Community 0`, `Community 2`, `Community 3`, `Community 5`, `Community 6`, `Community 7`, `Community 8`, `Community 10`, `Community 12`?**
  _High betweenness centrality (0.367) - this node is a cross-community bridge._
- **Why does `Draft` connect `Community 2` to `Community 0`, `Community 1`, `Community 3`, `Community 7`, `Community 11`?**
  _High betweenness centrality (0.273) - this node is a cross-community bridge._
- **Why does `cmd_daily()` connect `Community 3` to `Community 1`, `Community 2`, `Community 4`, `Community 5`, `Community 10`, `Community 12`?**
  _High betweenness centrality (0.118) - this node is a cross-community bridge._
- **Are the 67 inferred relationships involving `Draft` (e.g. with `MCP server exposing the LinkedIn pipeline as agent tools.  Run with:     python` and `Lightweight namespace for hermes CLI command helpers.`) actually correct?**
  _`Draft` has 67 INFERRED edges - model-reasoned connections that need verification._
- **Are the 66 inferred relationships involving `Item` (e.g. with `MCP server exposing the LinkedIn pipeline as agent tools.  Run with:     python` and `Lightweight namespace for hermes CLI command helpers.`) actually correct?**
  _`Item` has 66 INFERRED edges - model-reasoned connections that need verification._
- **Are the 26 inferred relationships involving `DirectLinkedInPublisher` (e.g. with `MCP server exposing the LinkedIn pipeline as agent tools.  Run with:     python` and `Lightweight namespace for hermes CLI command helpers.`) actually correct?**
  _`DirectLinkedInPublisher` has 26 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `cmd_daily()` (e.g. with `ensure_dirs()` and `init_db()`) actually correct?**
  _`cmd_daily()` has 15 INFERRED edges - model-reasoned connections that need verification._