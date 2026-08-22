# Source Map — Fully Automated, Zero Manual Drop

**Constraint:** No manual dropping. Every source must be automatically scrapable from the VPS using free feeds/APIs.

**Status of social sources:**
- ❌ Reddit: blocked (403) from VPS
- ❌ LinkedIn profiles: login wall / bot-gated
- ❌ Instagram: no public RSS/API, bot-gated
- ❌ YouTube channel RSS: bot-gated from VPS
- ❌ Nitter/X instances: unreliable and often block datacenter IPs

**Conclusion:** The automated pipeline will rely on **RSS feeds, public APIs, GitHub, arXiv, and blogs**. Trending social content must be discovered indirectly through these surfaces (e.g., when Hacker News, TechCrunch, or newsletters talk about a viral launch).

---

## 1. Auto-Scannable Sources

### A. General AI News + Aggregators

| # | Source | Feed / API | Frequency |
|---|--------|------------|-----------|
| 1 | **Hacker News** | `https://news.ycombinator.com/rss` | 2x daily |
| 2 | **TechCrunch AI** | `https://techcrunch.com/category/artificial-intelligence/feed/` | 2x daily |
| 3 | **The Verge AI** | `https://www.theverge.com/ai-artificial-intelligence/rss/index.xml` | 2x daily |
| 4 | **Wired AI** | `https://www.wired.com/tag/artificial-intelligence/feed/` | 2x daily |
| 5 | **MIT Technology Review** | `https://www.technologyreview.com/feed/` | 2x daily |
| 6 | **VentureBeat AI** | `https://venturebeat.com/category/ai/feed/` | 2x daily |

### B. Newsletters + Blogs

| # | Source | Feed | Frequency |
|---|--------|------|-----------|
| 7 | **Simon Willison** | `https://simonwillison.net/atom.xml` | 2x daily |
| 8 | **Latent Space** | `https://www.latent.space/feed` | 2x daily |
| 9 | **The Batch** | `https://www.deeplearning.ai/the-batch/feed` | 2x daily |
| 10 | **Import AI** | `https://importai.substack.com/feed` | 2x daily |
| 11 | **One Useful Thing** | `https://www.oneusefulthing.org/feed` | 2x daily |
| 12 | **AI Supremacy** | `https://aisupremacy.substack.com/feed` | 2x daily |
| 13 | **The Algorithm** | `https://www.technologyreview.com/tag/the-algorithm/feed/` | 2x daily |
| 14 | **Lilian Weng** | `https://lilianweng.github.io/index.xml` | 2x daily |
| 15 | **Eugene Yan** | `https://eugeneyan.com/rss.xml` | 2x daily |

### C. Research

| # | Source | Feed / API | Frequency |
|---|--------|------------|-----------|
| 16 | **arXiv AI (cs.AI)** | `https://export.arxiv.org/rss/cs.AI` | 2x daily |
| 17 | **arXiv Security (cs.CR)** | `https://export.arxiv.org/rss/cs.CR` | 2x daily |
| 18 | **arXiv ML (cs.LG)** | `https://export.arxiv.org/rss/cs.LG` | 2x daily |
| 19 | **arXiv SE (cs.SE)** | `https://export.arxiv.org/rss/cs.SE` | 2x daily |
| 20 | **Papers with Code** | `https://paperswithcode.com/rss` | 2x daily |

### D. Security

| # | Source | Feed | Frequency |
|---|--------|------|-----------|
| 21 | **The Hacker News** | `https://thehackernews.com/feeds/posts/default` | 2x daily |
| 22 | **PortSwigger Research** | `https://portswigger.net/research/rss` | 2x daily |
| 23 | **SANS ISC** | `https://isc.sans.edu/rssfeed.xml` | 2x daily |
| 24 | **BleepingComputer** | `https://www.bleepingcomputer.com/feed/` | 2x daily |

### E. Products + Builders

| # | Source | Feed | Frequency |
|---|--------|------|-----------|
| 25 | **Product Hunt AI** | `https://www.producthunt.com/feed?t=ai` | 2x daily |
| 26 | **Indie Hackers** | `https://www.indiehackers.com/feed` | 2x daily |

### F. Code / GitHub

| # | Source | API / Scrape | Frequency |
|---|--------|--------------|-----------|
| 27 | **GitHub Trending Python** | `https://github.com/trending/python?since=daily` (HTML) | 2x daily |
| 28 | **GitHub Trending Go** | `https://github.com/trending/go?since=daily` (HTML) | 2x daily |
| 29 | **GitHub Trending TypeScript** | `https://github.com/trending/typescript?since=daily` (HTML) | 2x daily |
| 30 | **GitHub Search: AI agents** | `https://api.github.com/search/repositories?q=ai+agent+created:>2026-08-15&sort=stars` | 2x daily |

---

## 2. What We Lose (and How to Replace It)

| Lost Source | Replacement Strategy |
|-------------|----------------------|
| LinkedIn profiles | Watch LinkedIn via newsletters/aggregators that quote LinkedIn posts |
| YouTube channels | Use YouTube creators' newsletters/blogs if they have them; skip auto extraction |
| Instagram | Skip — no reliable automation at zero cost |
| Reddit | Use Hacker News as the Reddit replacement for builder discussions |
| X/Twitter | Use Nitter sparingly; rely on journalists/bloggers who quote tweets |

---

## 3. Database Design (Free Options)

### Option A: SQLite (now)
- File: `/opt/data/content-pipeline/content.db`
- Good for 100k+ items easily
- Risk: grows on VPS disk

### Option B: Supabase (free tier, 500 MB)
- Hosted PostgreSQL
- Better long-term
- Can migrate SQLite → Supabase later

### Option C: Neon (free tier, 512 MB)
- Serverless PostgreSQL
- Good if we want to keep everything off the VPS

**Recommendation:** Keep SQLite for now, but design the schema so migration to Postgres/Supabase is one script.

### Core Tables

```sql
CREATE TABLE items (
    id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    item_url TEXT NOT NULL UNIQUE,
    item_title TEXT NOT NULL,
    item_author TEXT,
    published_at TEXT,
    collected_at TEXT NOT NULL,
    source_type TEXT NOT NULL,
    content_type TEXT,
    summary TEXT,
    key_claims TEXT,
    raw_content TEXT,
    pillar_candidates TEXT,
    topics TEXT,
    status TEXT DEFAULT 'raw',
    signal_strength TEXT,
    url_hash TEXT NOT NULL
);

CREATE INDEX idx_items_collected ON items(collected_at);
CREATE INDEX idx_items_status ON items(status);
CREATE INDEX idx_items_source ON items(source_name);
```

Markdown files remain the source of truth; SQLite is for fast queries and scoring later.

---

## 4. Updated Collector Architecture

```
Cron 08:00, 18:00 UTC
    |
    v
collect.py
    |
    +-- RSS feeds (feedparser)
    +-- GitHub trending (requests + BeautifulSoup)
    +-- GitHub search API (requests)
    |
    v
Normalize metadata
    |
    v
Deduplicate by URL hash
    |
    v
Save to:
    - Markdown: /opt/data/content-pipeline/raw/<YYYY-MM-DD>/<source>/<file>.md
    - SQLite: content.db (optional)
```

---

## 5. Token Optimization Rules (reminder)

- Truncate raw content to ~800 tokens
- Keep summary ≤ 400 chars
- Keep key claims ≤ 5 bullet points
- Store full links but not full article text
- One item = one file = one DB row

---

**Next step:** Update `sources.csv` and `collect.py` to use only auto sources, add SQLite, and run a full test.
