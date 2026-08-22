"""Hermes orchestrator: collect -> score -> draft -> queue -> (human approves) -> publish."""
import argparse
import csv
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests
from bs4 import BeautifulSoup

from config.settings import (
    DATA_DIR,
    LINKEDIN_CLIENT_ID,
    LINKEDIN_CLIENT_SECRET,
    LINKEDIN_REDIRECT_URI,
    MAX_RAW_CHARS,
    NEWSLETTER_DIR,
    QUEUE_DIR,
    RAW_DIR,
    REQUIRE_APPROVAL,
    SOURCES_CSV,
    ensure_dirs,
)
from pipeline.approval import approve_draft, list_pending, list_ready_to_publish, mark_published
from pipeline.collectors.instagram import collect_instagram
from pipeline.collectors.reddit import REDDIT_COMMUNITIES, collect_reddit
from pipeline.collectors.youtube import YOUTUBE_CHANNELS, collect_youtube
from pipeline.drafting import Draft, compile_newsletter, draft_item, save_draft
from pipeline.publishers.composio import (
    ComposioLinkedInPublisher,
    ComposioTwitterPublisher,
    get_composio_linkedin_publisher,
    get_composio_twitter_publisher,
)
from pipeline.publishers.linkedin import DirectLinkedInPublisher, DryRunPublisher, get_publisher
from pipeline.scoring import is_worthy, score_item
from pipeline.storage import Item, init_db, item_exists, save_item, update_status
from pipeline.tokens import clear_tokens, load_tokens, save_tokens

# Publishing targets controlled by CLI args and env
_PUBLISH_TARGETS = {
    "linkedin": get_composio_linkedin_publisher,
    "twitter": get_composio_twitter_publisher,
}


REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_CSV = REPO_ROOT / "sources.csv"

_session = requests.Session()
_session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    }
)
_adapter = requests.adapters.HTTPAdapter(max_retries=0, pool_connections=10, pool_maxsize=10)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(text: str, max_len: int = 60) -> str:
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[-\s]+", "-", text)
    return text[:max_len]


def extract_with_jina(url: str, timeout: int = 20) -> str:
    try:
        r = _session.get(
            f"https://r.jina.ai/{url}",
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200 and "blocked" not in r.text.lower():
            return re.sub(r"\n{3,}", "\n\n", r.text.strip())[:MAX_RAW_CHARS]
    except Exception as e:
        print(f"  jina error: {e}")
    return ""


def fetch_feed(url: str, timeout: int = 10):
    try:
        r = _session.get(url, timeout=timeout)
        r.raise_for_status()
        return feedparser.parse(r.content)
    except Exception as e:
        print(f"  feed error: {e}")
        return None


def extract_claims(text: str) -> list[str]:
    claims = []
    keywords = [
        "released", "launched", "announced", "introduces", "new", "model",
        "agent", "vulnerability", "attack", "benchmark", "api", "tool",
        "framework", "llm", "mcp", "rag",
    ]
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if any(kw in sentence.lower() for kw in keywords):
            s = sentence.strip()
            if len(s) > 20:
                claims.append(s)
        if len(claims) >= 5:
            break
    return claims


def normalize_feed_entry(name: str, url: str, entry, content_type: str, dry_run: bool = False) -> Item:
    link = entry.get("link", "")
    if not link and entry.get("links"):
        for l in entry.links:
            if l.get("rel") == "alternate":
                link = l.get("href", "")
                break
    if "arxiv.org/abs/" in link:
        link = link.replace("/pdf/", "/abs/")

    summary = entry.get("summary", "") or ""
    raw = summary
    if not dry_run and len(raw.split()) < 50 and link:
        ext = extract_with_jina(link)
        if ext:
            raw = ext
    raw = raw[:MAX_RAW_CHARS]

    return Item(
        id="",
        source_name=name,
        source_url=url,
        item_url=link,
        item_title=entry.get("title", "Untitled"),
        item_author=entry.get("author", ""),
        published_at=entry.get("published", ""),
        source_type="rss",
        content_type=content_type,
        summary=summary,
        key_claims=extract_claims(raw),
        raw_content=raw,
    )


def collect_rss(name: str, url: str, content_type: str, dry_run: bool = False, limit: int = 10) -> int:
    print(f"\n[{name}] {url}")
    feed = fetch_feed(url)
    if not feed or not feed.entries:
        print("  no entries")
        return 0

    count = 0
    for entry in feed.entries[:limit]:
        item = normalize_feed_entry(name, url, entry, content_type, dry_run=dry_run)
        if not item.item_url or item_exists(item.item_url):
            print(f"  dedupe: {item.item_title[:60]}")
            continue
        if not dry_run:
            save_item(item)
        print(f"  saved: {item.item_title[:60]}")
        count += 1
    print(f"  {count} new")
    return count


def collect_github_trending(language: str, dry_run: bool = False, limit: int = 10) -> int:
    url = f"https://github.com/trending/{language}?since=daily"
    print(f"\n[GitHub Trending {language}] {url}")
    try:
        r = _session.get(url, timeout=10)
        if r.status_code != 200:
            print(f"  HTTP {r.status_code}")
            return 0
        soup = BeautifulSoup(r.text, "html.parser")
        repos = []
        for article in soup.find_all("article")[:limit * 2]:
            link = article.find("h2")
            if link:
                a = link.find("a")
                if a and a.get("href"):
                    repos.append(a["href"].strip("/"))
            if len(repos) >= limit:
                break
        count = 0
        for repo in repos[:limit]:
            item_url = f"https://github.com/{repo}"
            if item_exists(item_url):
                print(f"  dedupe: {repo}")
                continue
            item = Item(
                id="",
                source_name=f"GitHub Trending {language}",
                source_url=url,
                item_url=item_url,
                item_title=repo,
                source_type="github-trending",
                content_type="repo",
                summary=f"Trending {language} repository on GitHub",
                key_claims=[f"{repo} is trending today on GitHub"],
                raw_content=repo,
            )
            if not dry_run:
                save_item(item)
            print(f"  saved: {repo}")
            count += 1
        print(f"  {count} new")
        return count
    except Exception as e:
        print(f"  error: {e}")
        return 0


def collect_github_search(query: str, dry_run: bool = False, limit: int = 10) -> int:
    url = f"https://api.github.com/search/repositories?q={query}&sort=stars&order=desc&per_page={limit}"
    print(f"\n[GitHub Search: {query}] {url}")
    try:
        r = _session.get(url, timeout=15)
        if r.status_code != 200:
            print(f"  HTTP {r.status_code}")
            return 0
        data = r.json()
        count = 0
        for repo in data.get("items", [])[:limit]:
            item_url = repo.get("html_url", "")
            if not item_url or item_exists(item_url):
                print(f"  dedupe: {repo.get('full_name', '')}")
                continue
            item = Item(
                id="",
                source_name=f"GitHub Search: {query}",
                source_url=url,
                item_url=item_url,
                item_title=repo.get("full_name", "Untitled"),
                source_type="github-search",
                content_type="repo",
                summary=repo.get("description", "") or "",
                key_claims=[repo.get("description", "") or "New GitHub repository"],
                raw_content=repo.get("description", "") or "",
            )
            if not dry_run:
                save_item(item)
            print(f"  saved: {repo.get('full_name', '')}")
            count += 1
        print(f"  {count} new")
        return count
    except Exception as e:
        print(f"  error: {e}")
        return 0


def cmd_collect(args) -> int:
    init_db()
    print(f"Starting collection at {now_iso()}")
    total = 0
    with SOURCES_CSV.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["name"]
            url_or_query = row["url"]
            source_type = row["type"]
            content_type = row["content_type"]
            if source_type == "rss":
                total += collect_rss(name, url_or_query, content_type, dry_run=args.dry_run, limit=args.limit)
            elif source_type == "github-trending":
                total += collect_github_trending(url_or_query, dry_run=args.dry_run, limit=args.limit)
            elif source_type == "github-search":
                total += collect_github_search(url_or_query, dry_run=args.dry_run, limit=args.limit)
    if not args.skip_reddit:
        total += collect_reddit(dry_run=args.dry_run, limit_per_sub=args.limit)
    if not args.skip_youtube:
        total += collect_youtube(dry_run=args.dry_run, limit_per_channel=args.limit)
    if not args.skip_instagram:
        total += collect_instagram(dry_run=args.dry_run, limit=args.limit)
    print(f"\nCollection complete: {total} new items")
    return 0


def cmd_youtube(args) -> int:
    init_db()
    total = collect_youtube(dry_run=args.dry_run, limit_per_channel=args.limit)
    print(f"\nYouTube collection complete: {total} new items")
    return 0


def cmd_instagram(args) -> int:
    init_db()
    total = collect_instagram(dry_run=args.dry_run, limit=args.limit)
    print(f"\nInstagram collection complete: {total} new items")
    return 0


def cmd_reddit(args) -> int:
    init_db()
    total = collect_reddit(dry_run=args.dry_run, limit_per_sub=args.limit)
    print(f"\nReddit collection complete: {total} new items")
    return 0


def cmd_score(args) -> int:
    init_db()
    items = []
    # In a real run we might load un-scored items; here score latest N
    from pipeline.storage import list_items
    items = list_items(limit=args.limit)
    worthy = 0
    for item in items:
        score = score_item(item)
        if is_worthy(item, min_confidence=args.min_confidence, min_signal=args.min_signal):
            worthy += 1
            update_status(item.item_url, "worthy")
            print(f"[WORTHY] {item.item_title[:70]} | {score.pillar} {score.pillar_confidence}% {score.signal_strength}%")
        else:
            update_status(item.item_url, "scored")
    print(f"\n{worthy} worthy items out of {len(items)}")
    return 0


def cmd_draft(args) -> int:
    init_db()
    from pipeline.storage import list_items
    items = [i for i in list_items(status="worthy", limit=args.limit) if i.status == "worthy"]
    if not items:
        print("No worthy items to draft. Run `score` first.")
        return 1
    for item in items:
        score = score_item(item)
        draft = draft_item(item, score)
        path = save_draft(draft, QUEUE_DIR)
        update_status(item.item_url, "drafted")
        print(f"Draft queued: {path.name}")
    return 0


def cmd_queue(args) -> int:
    pending = list_pending()
    ready = list_ready_to_publish()
    print(f"Pending approval: {len(pending)}")
    for d in pending[:args.limit]:
        print(f"  - {d.item_id} [{d.pillar}] {d.linkedin_post[:80]}...")
    print(f"Ready to publish: {len(ready)}")
    for d in ready[:args.limit]:
        print(f"  - {d.item_id} [{d.pillar}]")
    return 0


def cmd_approve(args) -> int:
    if approve_draft(args.item_id):
        print(f"Approved {args.item_id}")
        return 0
    print(f"Draft not found: {args.item_id}")
    return 1


def cmd_newsletter(args) -> int:
    ensure_dirs()
    from pipeline.storage import list_items
    items = [i for i in list_items(status="worthy", limit=args.limit) if i.status == "worthy"]
    if not items:
        print("No worthy items found for newsletter. Run `collect` and `score` first.")
        return 0

    drafts = []
    for item in items:
        score = score_item(item)
        draft = draft_item(item, score)
        drafts.append(draft)

    newsletter = compile_newsletter(drafts, title=args.title)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    filename = f"{ts}--newsletter.md"
    path = NEWSLETTER_DIR / filename
    path.write_text(newsletter)
    print(f"Newsletter compiled: {path}")
    print(f"Sections: {len(drafts)}")
    return 0


def cmd_publish(args) -> int:
    ensure_dirs()
    ready = list_ready_to_publish()
    if not ready:
        print("No approved drafts ready to publish.")
        return 0

    target = getattr(args, "target", "linkedin").lower()
    publisher_factory = _PUBLISH_TARGETS.get(target)
    if not publisher_factory:
        print(f"Unknown publish target: {target}", file=sys.stderr)
        return 1

    publisher = publisher_factory() or DryRunPublisher()
    print(f"Publisher: {publisher.__class__.__name__}")
    published_count = 0
    for draft in ready[:args.limit]:
        if args.dry_run:
            print(f"[DRY-RUN] Would {target}-publish: {draft.item_id}")
            result = {"ok": True, "dry_run": True, "target": target}
        else:
            result = publisher.publish(draft)
        if result.get("ok"):
            mark_published(draft.item_id)
            update_status(draft.source_url, "published")
            published_count += 1
            print(f"Published {draft.item_id} to {target}: {result}")
        else:
            print(f"Failed {draft.item_id} to {target}: {result}")
    print(f"\nPublished {published_count} draft(s) to {target}")
    return 0


def cmd_linkedin_auth_url(args) -> int:
    if not LINKEDIN_CLIENT_ID or not LINKEDIN_REDIRECT_URI:
        print("LINKEDIN_CLIENT_ID and LINKEDIN_REDIRECT_URI must be set.", file=sys.stderr)
        return 1
    url = DirectLinkedInPublisher.authorization_url(state=args.state)
    print("Open this URL in your browser and authorize the app:")
    print(url)
    print("\nAfter authorization, LinkedIn will redirect to your callback URL with a `code` parameter.")
    print("Run: python run.py linkedin-exchange --code CODE")
    return 0


def cmd_linkedin_exchange(args) -> int:
    if not LINKEDIN_CLIENT_ID or not LINKEDIN_CLIENT_SECRET or not LINKEDIN_REDIRECT_URI:
        print("LinkedIn OAuth credentials are incomplete.", file=sys.stderr)
        return 1
    try:
        resp = DirectLinkedInPublisher.exchange_code(args.code)
    except Exception as e:
        print(f"Token exchange failed: {e}", file=sys.stderr)
        return 1

    access_token = resp.get("access_token")
    refresh_token = resp.get("refresh_token", "")
    expires_in = resp.get("expires_in", 0)
    if not access_token:
        print("No access_token in response.", file=sys.stderr)
        return 1

    pub = DirectLinkedInPublisher(access_token=access_token, author_urn="")
    author_urn = pub.fetch_author_urn()
    if not author_urn:
        print("Warning: could not fetch author URN. Publishing will retry at publish time.", file=sys.stderr)

    save_tokens(access_token, refresh_token, expires_in, author_urn or "")
    print("LinkedIn tokens saved successfully.")
    if author_urn:
        print(f"Author URN: {author_urn}")
    return 0


def cmd_linkedin_status(args) -> int:
    tokens = load_tokens()
    if not tokens:
        print("No LinkedIn tokens stored.")
        return 0
    print(f"Access token present: {bool(tokens.get('access_token'))}")
    print(f"Refresh token present: {bool(tokens.get('refresh_token'))}")
    print(f"Author URN: {tokens.get('author_urn') or 'not set'}")
    return 0


def cmd_linkedin_logout(args) -> int:
    clear_tokens()
    print("LinkedIn tokens cleared.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hermes", description="LinkedIn content pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Do not persist anything external")
    sub = parser.add_subparsers(dest="command")

    p_collect = sub.add_parser("collect", help="Collect new items from sources")
    p_collect.add_argument("--skip-reddit", action="store_true", help="Skip Reddit collection")
    p_collect.add_argument("--skip-youtube", action="store_true", help="Skip YouTube collection")
    p_collect.add_argument("--skip-instagram", action="store_true", help="Skip Instagram collection")
    p_collect.add_argument("--limit", type=int, default=10)
    p_collect.set_defaults(func=cmd_collect)

    p_reddit = sub.add_parser("reddit", help="Collect top posts from Reddit via Composio")
    p_reddit.add_argument("--limit", type=int, default=10)
    p_reddit.add_argument("--dry-run", action="store_true")
    p_reddit.set_defaults(func=cmd_reddit)

    p_youtube = sub.add_parser("youtube", help="Collect recent videos from YouTube channels via Composio")
    p_youtube.add_argument("--limit", type=int, default=3)
    p_youtube.add_argument("--dry-run", action="store_true")
    p_youtube.set_defaults(func=cmd_youtube)

    p_instagram = sub.add_parser("instagram", help="Collect recent media from Instagram via Composio")
    p_instagram.add_argument("--limit", type=int, default=5)
    p_instagram.add_argument("--dry-run", action="store_true")
    p_instagram.set_defaults(func=cmd_instagram)

    p_score = sub.add_parser("score", help="Score collected items")
    p_score.add_argument("--limit", type=int, default=100)
    p_score.add_argument("--min-confidence", type=int, default=50)
    p_score.add_argument("--min-signal", type=int, default=40)
    p_score.set_defaults(func=cmd_score)

    p_draft = sub.add_parser("draft", help="Draft posts for worthy items")
    p_draft.add_argument("--limit", type=int, default=5)
    p_draft.set_defaults(func=cmd_draft)

    p_newsletter = sub.add_parser("newsletter", help="Compile a newsletter from worthy items")
    p_newsletter.add_argument("--limit", type=int, default=5)
    p_newsletter.add_argument("--title", default="Secure AI Engineering Weekly")
    p_newsletter.set_defaults(func=cmd_newsletter)

    p_queue = sub.add_parser("queue", help="Show approval queue")
    p_queue.add_argument("--limit", type=int, default=20)
    p_queue.set_defaults(func=cmd_queue)

    p_approve = sub.add_parser("approve", help="Approve a draft by item_id")
    p_approve.add_argument("item_id")
    p_approve.set_defaults(func=cmd_approve)

    p_publish = sub.add_parser("publish", help="Publish approved drafts")
    p_publish.add_argument("--target", choices=["linkedin", "twitter"], default="linkedin")
    p_publish.add_argument("--limit", type=int, default=1)
    p_publish.set_defaults(func=cmd_publish)

    p_auth = sub.add_parser("linkedin-auth-url", help="Print LinkedIn OAuth URL")
    p_auth.add_argument("--state", default="hermes")
    p_auth.set_defaults(func=cmd_linkedin_auth_url)

    p_exchange = sub.add_parser("linkedin-exchange", help="Exchange LinkedIn auth code for tokens")
    p_exchange.add_argument("--code", required=True)
    p_exchange.set_defaults(func=cmd_linkedin_exchange)

    p_status = sub.add_parser("linkedin-status", help="Show stored LinkedIn token status")
    p_status.set_defaults(func=cmd_linkedin_status)

    p_logout = sub.add_parser("linkedin-logout", help="Clear stored LinkedIn tokens")
    p_logout.set_defaults(func=cmd_linkedin_logout)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
