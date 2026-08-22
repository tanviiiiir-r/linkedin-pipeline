#!/usr/bin/env python3
"""
content-pipeline collector — fully automated, zero manual drops
Scan RSS feeds, GitHub trending, and GitHub search twice daily.
Save raw items as structured markdown + SQLite for fast queries.
"""

import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests
from bs4 import BeautifulSoup

ROOT = Path("/opt/data/content-pipeline")
RAW_DIR = ROOT / "raw"
SOURCES_CSV = ROOT / "sources.csv"
DB_PATH = ROOT / "content.db"

MAX_RAW_TOKENS = 800
TOKEN_RATIO = 0.4


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(text: str, max_len=60) -> str:
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[-\s]+", "-", text)
    return text[:max_len]


def estimate_tokens(text: str) -> int:
    return int(len(text) * TOKEN_RATIO)


def truncate_text(text: str, max_tokens=MAX_RAW_TOKENS) -> str:
    if not text:
        return ""
    if estimate_tokens(text) <= max_tokens:
        return text.strip()
    limit = int(max_tokens / TOKEN_RATIO)
    return text[:limit].rsplit(" ", 1)[0] + "\n\n[truncated]"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS items (
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
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_collected ON items(collected_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_status ON items(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_source ON items(source_name)")
    conn.commit()
    conn.close()


def url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def item_exists(url: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT 1 FROM items WHERE item_url = ? OR url_hash = ?", (url, url_hash(url)))
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def extract_with_jina(url: str, timeout=20) -> str:
    try:
        r = requests.get(
            f"https://r.jina.ai/{url}",
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200 and "You've been blocked" not in r.text:
            return re.sub(r"\n{3,}", "\n\n", r.text.strip())
    except Exception as e:
        print(f"  jina error: {e}")
    return ""


def fetch_feed(url: str, timeout=20):
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        return feedparser.parse(r.content)
    except Exception as e:
        print(f"  feed error: {e}")
        return None


def extract_claims(text: str) -> list:
    claims = []
    keywords = ["released", "launched", "announced", "introduces", "new", "model", "agent", "vulnerability", "attack", "benchmark", "api", "tool", "framework", "llm", "mcp", "rag"]
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if any(kw in sentence.lower() for kw in keywords):
            s = sentence.strip()
            if len(s) > 20:
                claims.append(s)
        if len(claims) >= 5:
            break
    return claims


def save_item(source_name: str, source_url: str, item_url: str, title: str, author: str, published: str, summary: str, content_type: str):
    if not item_url:
        return None
    if item_exists(item_url):
        print(f"  dedupe: {title[:60]}")
        return None

    body = summary or ""
    if estimate_tokens(body) < 200:
        ext = extract_with_jina(item_url)
        if ext:
            body = ext

    body = truncate_text(body)
    claims = extract_claims(body)

    item_id = url_hash(item_url)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    source_slug = slugify(source_name)
    out_dir = RAW_DIR / today / source_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%H%M%S")
    filename = f"{ts}--{item_id}--{slugify(title)}.md"

    frontmatter = {
        "id": item_id,
        "source_name": source_name,
        "source_url": source_url,
        "item_url": item_url,
        "item_title": title,
        "item_author": author,
        "published_at": published,
        "collected_at": now_iso(),
        "source_type": "rss",
        "content_type": content_type,
        "pillar_candidates": [],
        "topics": [],
        "status": "raw",
        "signal_strength": "auto",
        "url_hash": item_id,
    }

    md = f"""---
{json.dumps(frontmatter, indent=2)}
---

## Summary
{summary[:500] if summary else "[No summary extracted]"}

## Key Claims
{chr(10).join(f"- {c}" for c in claims[:5]) or "- [No claims extracted]"}

## Links
- Primary source: {item_url}
- Feed source: {source_url}

## Raw Content
{body}
"""

    (out_dir / filename).write_text(md)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO items (id, source_name, source_url, item_url, item_title, item_author, published_at, collected_at,
                           source_type, content_type, summary, key_claims, raw_content, pillar_candidates, topics,
                           status, signal_strength, url_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        item_id, source_name, source_url, item_url, title, author, published, now_iso(),
        "rss", content_type, summary, json.dumps(claims), body, json.dumps([]), json.dumps([]),
        "raw", "auto", item_id
    ))
    conn.commit()
    conn.close()

    print(f"  saved: {filename}")
    return out_dir / filename


def collect_rss(name: str, url: str, content_type: str = "article"):
    print(f"\n[{name}] {url}")
    feed = fetch_feed(url)
    if not feed or not feed.entries:
        print("  no entries")
        return 0

    count = 0
    for entry in feed.entries[:15]:
        link = entry.get("link", "")
        if not link and entry.get("links"):
            for l in entry.links:
                if l.get("rel") == "alternate":
                    link = l.get("href", "")
                    break

        if "arxiv.org/abs/" in link:
            link = link.replace("/pdf/", "/abs/")

        if save_item(
            source_name=name,
            source_url=url,
            item_url=link,
            title=entry.get("title", "Untitled"),
            author=entry.get("author", ""),
            published=entry.get("published", ""),
            summary=entry.get("summary", ""),
            content_type=content_type,
        ):
            count += 1
    print(f"  {count} new")
    return count


def collect_github_trending(language: str):
    url = f"https://github.com/trending/{language}?since=daily"
    print(f"\n[GitHub Trending {language}] {url}")
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            print(f"  HTTP {r.status_code}")
            return 0
        soup = BeautifulSoup(r.text, "lxml")
        repos = soup.select("article.Box h2 a")
        count = 0
        for repo in repos[:10]:
            href = "https://github.com" + repo.get("href", "")
            title = repo.get_text(strip=True).replace("\n", "").replace(" ", " ")
            if save_item(
                source_name=f"GitHub Trending {language}",
                source_url=url,
                item_url=href,
                title=title,
                author="",
                published="",
                summary=f"Trending {language} repository on GitHub today.",
                content_type="repo",
            ):
                count += 1
        print(f"  {count} new")
        return count
    except Exception as e:
        print(f"  error: {e}")
        return 0


def collect_github_search(query: str):
    url = f"https://api.github.com/search/repositories?q={query}&sort=stars&order=desc&per_page=10"
    print(f"\n[GitHub Search: {query}] {url}")
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "secure-ai-builder-collector", "Accept": "application/vnd.github+json"})
        if r.status_code != 200:
            print(f"  HTTP {r.status_code}: {r.text[:200]}")
            return 0
        data = r.json()
        count = 0
        for item in data.get("items", []):
            if save_item(
                source_name=f"GitHub Search: {query}",
                source_url=url,
                item_url=item.get("html_url", ""),
                title=item.get("full_name", "Untitled"),
                author=item.get("owner", {}).get("login", ""),
                published=item.get("created_at", ""),
                summary=item.get("description", "") or "",
                content_type="repo",
            ):
                count += 1
        print(f"  {count} new")
        return count
    except Exception as e:
        print(f"  error: {e}")
        return 0


def main():
    if not SOURCES_CSV.exists():
        print(f"Sources file not found: {SOURCES_CSV}")
        sys.exit(1)

    init_db()

    with SOURCES_CSV.open() as f:
        sources = list(csv.DictReader(f))

    total = 0
    print(f"Starting collection at {now_iso()}")

    for src in sources:
        stype = src.get("type", "rss")
        if stype == "rss":
            total += collect_rss(src["name"], src["url"], src.get("content_type", "article"))
        elif stype == "github-trending":
            total += collect_github_trending(src["url"])
        elif stype == "github-search":
            total += collect_github_search(src["url"])

    print(f"\nDone at {now_iso()}. Total new items: {total}")


if __name__ == "__main__":
    main()
