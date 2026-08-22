# linkedin-pipeline

Hermes-driven content pipeline for AI builders. Collects from RSS feeds, GitHub, and news sources, scores items against content pillars, drafts LinkedIn posts + newsletter snippets, and publishes through a human-in-the-loop approval queue.

## Quick start

```bash
# Install dependencies
python -m pip install -r requirements.txt

# Copy env template and fill in LinkedIn credentials
cp .env.example .env

# Run a dry-run collection
python run.py --dry-run collect --limit 3

# Score collected items
python run.py score --limit 50

# Draft the top worthy item into the approval queue
python run.py draft

# Show pending drafts
python run.py queue

# Approve a draft (replace <item_id> with the real id)
python run.py approve <item_id>

# Publish approved drafts (uses LinkedIn auth if configured, else dry-run)
python run.py publish --limit 1
```

## Project layout

```
config/settings.py          # Environment + settings
pipeline/
  hermes.py                 # CLI orchestrator
  storage.py                # SQLite + markdown persistence
  scoring.py                # Pillar + signal scoring
  drafting.py               # LinkedIn + newsletter drafts
  approval.py               # Human-in-the-loop queue helpers
  publishers/
    linkedin.py             # Composio + direct LinkedIn OAuth adapters
scripts/
  collect.py                # Original standalone collector (legacy)
tests/                      # pytest suite
```

## LinkedIn auth

Recommended path: [Composio](https://composio.dev). Set `COMPOSIO_API_KEY` in `.env`.

Alternative: direct LinkedIn OAuth. Set `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`, and `LINKEDIN_REDIRECT_URI`.

Without credentials the publisher runs in **dry-run mode** so the rest of the pipeline can be tested safely.

## Hermes LLM integration

The current drafting layer is rule-based. Hermes will later replace `draft_item()` with an LLM-driven humanizer. The interface is kept simple so swapping the implementation is one function change.
