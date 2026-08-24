"""Hermes orchestrator: collect -> score -> draft -> queue -> (human approves) -> publish."""
import argparse
import csv
import logging
import os
import re
import sys
from datetime import datetime, timezone

import feedparser
import requests
from bs4 import BeautifulSoup

from config.calendar import day_plan
from config.settings import (
    DATA_DIR,
    LINKEDIN_CLIENT_ID,
    LINKEDIN_CLIENT_SECRET,
    LINKEDIN_REDIRECT_URI,
    MAX_RAW_CHARS,
    NEWSLETTER_DIR,
    QUEUE_DIR,
    SOURCES_CSV,
    ensure_dirs,
)
from pipeline.approval import approve_draft, list_pending, list_ready_to_publish, mark_published
from pipeline.calendar import select_for_today
from pipeline.checkpoints import write_daily_checkpoint
from pipeline.collectors.instagram import collect_instagram
from pipeline.collectors.reddit import collect_reddit
from pipeline.collectors.youtube import collect_youtube
from pipeline.content_analyst import run_analysis
from pipeline.dedupe import find_duplicate
from pipeline.drafting import Draft, compile_newsletter, draft_item, load_drafts, save_draft
from pipeline.drafting_v2 import draft_item_v2
from pipeline.image_engine import image_for_post
from pipeline.invariants import run_health_checks
from pipeline.log import setup_logging
from pipeline.publishers.composio import (
    get_composio_linkedin_publisher,
    get_composio_twitter_publisher,
)
from pipeline.publishers.linkedin import DirectLinkedInPublisher, DryRunPublisher
from pipeline.review_dashboard import generate_dashboard
from pipeline.review_server import run_server
from pipeline.scoring import is_worthy, score_item
from pipeline.storage import Item, init_db, item_exists, list_items, save_item, update_status
from pipeline.tokens import clear_tokens, load_tokens, save_tokens
from pipeline.topics import extract_topics
from pipeline.verify import format_verdict, verify_draft

setup_logging()
logger = logging.getLogger(__name__)

# Publishing targets controlled by CLI args and env
_PUBLISH_TARGETS = {
    "linkedin": get_composio_linkedin_publisher,
    "twitter": get_composio_twitter_publisher,
}


_session = requests.Session()
_session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    }
)
_adapter = requests.adapters.HTTPAdapter(max_retries=0, pool_connections=10, pool_maxsize=10)
_session.mount("https://", _adapter)
if os.getenv("ALLOW_HTTP", "").lower() in ("1", "true", "yes"):
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
    except requests.RequestException as e:
        print(f"  jina error: {e}")
    return ""


def fetch_feed(url: str, timeout: int = 10):
    try:
        r = _session.get(url, timeout=timeout)
        r.raise_for_status()
        return feedparser.parse(r.content)
    except requests.RequestException as e:
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

    title = entry.get("title", "Untitled")
    full_text = f"{title}\n\n{raw}"
    topics = extract_topics(full_text, top_n=5)

    return Item(
        id="",
        source_name=name,
        source_url=url,
        item_url=link,
        item_title=title,
        item_author=entry.get("author", ""),
        published_at=entry.get("published", ""),
        source_type="rss",
        content_type=content_type,
        summary=summary,
        key_claims=extract_claims(raw),
        raw_content=raw,
        topics=topics,
    )


def collect_rss(name: str, url: str, content_type: str, dry_run: bool = False, limit: int = 10) -> int:
    print(f"\n[{name}] {url}")
    feed = fetch_feed(url)
    if not feed or not feed.entries:
        print("  no entries")
        return 0

    # Load recent items for semantic dedupe
    recent_items = list_items(limit=500) if not dry_run else []

    count = 0
    for entry in feed.entries[:limit]:
        item = normalize_feed_entry(name, url, entry, content_type, dry_run=dry_run)
        if not item.item_url or item_exists(item.item_url):
            print(f"  dedupe: {item.item_title[:60]}")
            continue
        if recent_items and find_duplicate(item, recent_items):
            print(f"  semantic dedupe: {item.item_title[:60]}")
            continue
        if not dry_run:
            save_item(item)
        print(f"  saved: {item.item_title[:60]} [{', '.join(item.topics[:3])}]")
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
    except requests.RequestException as e:
        logger.warning("GitHub trending collection failed: %s", e)
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
    except requests.RequestException as e:
        logger.warning("GitHub search collection failed: %s", e)
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
            try:
                if source_type == "rss":
                    total += collect_rss(name, url_or_query, content_type, dry_run=args.dry_run, limit=args.limit)
                elif source_type == "github-trending":
                    total += collect_github_trending(url_or_query, dry_run=args.dry_run, limit=args.limit)
                elif source_type == "github-search":
                    total += collect_github_search(url_or_query, dry_run=args.dry_run, limit=args.limit)
            except (RuntimeError, requests.exceptions.RequestException, OSError):
                logger.exception("Source %s failed", name)
    if not args.skip_reddit:
        try:
            total += collect_reddit(dry_run=args.dry_run, limit_per_sub=args.limit)
        except (RuntimeError, requests.exceptions.RequestException, OSError):
            logger.exception("Reddit collection failed")
    if not args.skip_youtube:
        try:
            total += collect_youtube(dry_run=args.dry_run, limit_per_channel=args.limit)
        except (RuntimeError, requests.exceptions.RequestException, OSError):
            logger.exception("YouTube collection failed")
    if not args.skip_instagram:
        try:
            total += collect_instagram(dry_run=args.dry_run, limit=args.limit)
        except (RuntimeError, requests.exceptions.RequestException, OSError):
            logger.exception("Instagram collection failed")
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


def cmd_daily(args) -> int:
    """End-to-end daily run: collect -> score -> draft -> verify -> newsletter -> checkpoint.
    Publishing is intentionally left out; it requires explicit human approval.
    """
    print(f"=== Daily run started at {now_iso()} ===")
    ensure_dirs()
    init_db()
    source_errors: list[str] = []

    # 1. Collect
    print("\n-- COLLECT --")
    collect_total = 0
    with SOURCES_CSV.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["name"]
            url_or_query = row["url"]
            source_type = row["type"]
            content_type = row["content_type"]
            try:
                if source_type == "rss":
                    collect_total += collect_rss(name, url_or_query, content_type, dry_run=args.dry_run, limit=args.collect_limit)
                elif source_type == "github-trending":
                    collect_total += collect_github_trending(url_or_query, dry_run=args.dry_run, limit=args.collect_limit)
                elif source_type == "github-search":
                    collect_total += collect_github_search(url_or_query, dry_run=args.dry_run, limit=args.collect_limit)
            except (RuntimeError, requests.exceptions.RequestException, OSError) as e:
                logger.exception("Source %s failed during daily run", name)
                source_errors.append(f"{name}: {e}")
    if not args.skip_reddit:
        try:
            collect_total += collect_reddit(dry_run=args.dry_run, limit_per_sub=args.collect_limit)
        except (RuntimeError, requests.exceptions.RequestException, OSError) as e:
            logger.exception("Reddit collection failed during daily run")
            source_errors.append(f"reddit: {e}")
    if not args.skip_youtube:
        try:
            collect_total += collect_youtube(dry_run=args.dry_run, limit_per_channel=args.collect_limit)
        except (RuntimeError, requests.exceptions.RequestException, OSError) as e:
            logger.exception("YouTube collection failed during daily run")
            source_errors.append(f"youtube: {e}")
    if not args.skip_instagram:
        try:
            collect_total += collect_instagram(dry_run=args.dry_run, limit=args.collect_limit)
        except (RuntimeError, requests.exceptions.RequestException, OSError) as e:
            logger.exception("Instagram collection failed during daily run")
            source_errors.append(f"instagram: {e}")
    print(f"\nCollection complete: {collect_total} new items")

    # 2. Score
    print("\n-- SCORE --")
    items = list_items(limit=200)
    worthy = 0
    for item in items:
        score = score_item(item)
        if score.topics:
            item.topics = score.topics
        if is_worthy(item, min_confidence=args.min_confidence, min_signal=args.min_signal):
            worthy += 1
            update_status(item.item_url, "worthy")
        else:
            update_status(item.item_url, "scored")
    print(f"{worthy} worthy items")

    # 3. Draft
    print("\n-- DRAFT --")
    worthy_items = [i for i in list_items(status="worthy", limit=args.draft_limit) if i.status == "worthy"]
    drafted = 0
    drafts: list[Draft] = []
    for item in worthy_items:
        score = score_item(item)
        draft = draft_item(item, score)
        save_draft(draft, QUEUE_DIR)
        update_status(item.item_url, "drafted")
        drafts.append(draft)
        drafted += 1
    print(f"Drafted {drafted} items")

    # 4. Verify drafts (L4-style)
    print("\n-- VERIFY --")
    verified = 0
    rejected = 0
    for draft in drafts:
        result = verify_draft(draft)
        print(f"  [{draft.item_id[:8]}] {result.verdict.value} ({result.score}/100) — {draft.title[:55]}")
        if result.verdict.value == "APPROVE":
            verified += 1
        elif result.verdict.value == "REJECT":
            rejected += 1

    # 5. Newsletter
    print("\n-- NEWSLETTER --")
    newsletter_drafts = []
    for item in [i for i in list_items(status="worthy", limit=args.newsletter_limit) if i.status == "worthy"]:
        score = score_item(item)
        newsletter_drafts.append(draft_item(item, score))
    if newsletter_drafts:
        newsletter = compile_newsletter(newsletter_drafts, title=args.newsletter_title)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        path = NEWSLETTER_DIR / f"{ts}--newsletter.md"
        path.write_text(newsletter)
        print(f"Newsletter saved: {path}")
    else:
        print("No worthy items for newsletter")

    # 6. Health checks
    print("\n-- HEALTH --")
    health_checks = run_health_checks(collected=collect_total, source_errors=source_errors)
    for c in health_checks:
        symbol = "✅" if c.passed else "❌"
        print(f"  {symbol} {c.name}: {c.message}")

    # 7. Checkpoint
    print("\n-- CHECKPOINT --")
    checkpoint_path = write_daily_checkpoint(
        collected=collect_total,
        worthy=worthy,
        drafted=drafted,
        newsletter_sections=len(newsletter_drafts),
        verified=verified,
        rejected=rejected,
        source_errors=source_errors,
        health_checks=health_checks,
        next_action="Review queue with `python run.py queue` and approve items to publish.",
    )
    print(f"Checkpoint saved: {checkpoint_path}")

    print(f"\n=== Daily run completed at {now_iso()} ===")
    return 0


# Notify stub (override later for Telegram/Discord)
def notify_daily_summary(collected: int, worthy: int, drafted: int, newsletter_sections: int) -> None:
    """Emit a daily summary notification. Default is stdout; override for Telegram/Discord."""
    msg = (
        f"Daily pipeline run complete.\n"
        f"Collected: {collected}\n"
        f"Worthy: {worthy}\n"
        f"Drafted: {drafted}\n"
        f"Newsletter sections: {newsletter_sections}\n"
        f"Next step: review queue with `python run.py queue` and approve items to publish."
    )
    log_path = DATA_DIR / "daily-runs"
    log_path.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    (log_path / f"{ts}.log").write_text(msg)
    print(msg)


def cmd_score(args) -> int:
    init_db()
    # By default score items that have not been scored yet so repeated runs make progress.
    status_filter = getattr(args, "status", None) or "raw"
    if status_filter == "all":
        status_filter = None
    items = list_items(status=status_filter, limit=args.limit)
    # Fallback to any items if no unscored/raw items remain.
    if not items:
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


def cmd_verify(args) -> int:
    """Verify queued or specified draft against quality gates."""
    init_db()
    drafts = load_drafts(QUEUE_DIR)
    target_id = getattr(args, "item_id", None)

    if target_id:
        drafts = [d for d in drafts if d.item_id == target_id or d.item_id.startswith(target_id)]

    if not drafts:
        print("No drafts found in queue. Run `draft` first.")
        return 1

    for draft in drafts[:args.limit]:
        result = verify_draft(draft)
        print(f"\n[{draft.item_id}] {draft.title}")
        print(format_verdict(result))
    return 0


def cmd_draft(args) -> int:
    init_db()
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




def cmd_draft_today(args) -> int:
    """Draft today's post using the LLM humanizer and the 7-day calendar."""
    init_db()
    ensure_dirs()
    from datetime import date as _date
    date_override = getattr(args, "date", None)
    target_date = _date.fromisoformat(date_override) if date_override else None
    plan = day_plan(target_date)
    dry_run = getattr(args, "dry_run", False)
    with_image = getattr(args, "with_image", False)
    force_comfy = getattr(args, "force_comfy", False)

    candidates = list_items(status="worthy", limit=args.limit * 5)
    if not candidates:
        # Fall back to recently collected raw items so the demo can still work.
        candidates = list_items(status=None, limit=args.limit * 5)
    if not candidates:
        print("No items to draft. Run `collect` and `score` first.")
        return 1

    selected = select_for_today(candidates, limit=args.limit, for_date=target_date)
    if not selected:
        print(f"No item matched today's plan ({plan.post_type}: {plan.job}).")
        return 1

    queued = 0
    for item, score in selected:
        draft = draft_item_v2(item, score, day_plan=plan)

        if with_image or force_comfy:
            img_path = image_for_post(
                item_url=item.item_url,
                title=draft.title,
                day=plan.day_name,
                pillar=plan.post_type,
                linkedin_post=draft.linkedin_post,
                hashtags=" ".join(draft.hashtags),
                skip_og=force_comfy,
            )
            if img_path:
                draft.image_path = str(img_path)
                # Persist image path on the source item so future drafts can reuse it
                item.image_path = str(img_path)
                try:
                    save_item(item)
                except (OSError, RuntimeError):
                    logger.exception("Failed to persist item image_path")

        if dry_run:
            print(f"\n--- DRY-RUN DRAFT ({plan.day_name}, {plan.post_type}) ---")
            print(f"Title: {draft.title}")
            print(f"Source: {draft.source_url}")
            print(f"Hashtags: {' '.join(draft.hashtags)}")
            if draft.image_path:
                print(f"Image: {draft.image_path}")
            print("\nLinkedIn post:")
            print(draft.linkedin_post)
            print("--- END DRY-RUN ---")
        else:
            path = save_draft(draft, QUEUE_DIR)
            update_status(item.item_url, "drafted")
            print(f"Draft queued: {path.name}")
        queued += 1
    print(f"\n{queued} draft(s) produced for {plan.day_name} ({plan.post_type}).")
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
    except (requests.exceptions.RequestException, RuntimeError, OSError) as e:
        logger.exception("LinkedIn token exchange failed")
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
        print("Error: could not fetch author URN. Tokens not saved.", file=sys.stderr)
        return 1

    save_tokens(access_token, refresh_token, expires_in, author_urn)
    print("LinkedIn tokens saved successfully.")
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




def cmd_review_dashboard(args) -> int:
    """Generate the static review dashboard HTML from pending drafts."""
    init_db()
    ensure_dirs()
    path = generate_dashboard()
    print(f"Review dashboard generated: {path}")
    print("Start server with: python run.py review-server")
    return 0


def cmd_review_server(args) -> int:
    """Start the tiny HTTP review server."""
    init_db()
    ensure_dirs()
    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8080)
    if host == "0.0.0.0":  # nosec B104
        print(
            "WARNING: review-server binds 0.0.0.0. "
            "Only expose this behind Traefik/basic-auth or a trusted network.",
            file=sys.stderr,
        )
    run_server(host=host, port=port)
    return 0


def cmd_analyze_content(args) -> int:
    """Run daily relevance + perfection analysis on queued drafts."""
    from datetime import date as _date
    date_override = getattr(args, "date", None)
    target_date = _date.fromisoformat(date_override) if date_override else None
    use_llm = not getattr(args, "no_llm", False)
    limit = getattr(args, "limit", 10)
    report_path = run_analysis(for_date=target_date, use_llm=use_llm, limit=limit)
    print(f"Analysis report saved: {report_path}")
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
    p_score.add_argument(
        "--status",
        default="raw",
        choices=["raw", "scored", "worthy", "all"],
        help="Only score items with this status (default: raw). Use 'all' to rescore everything.",
    )
    p_score.set_defaults(func=cmd_score)

    p_draft = sub.add_parser("draft", help="Draft posts for worthy items")
    p_draft.add_argument("--limit", type=int, default=5)
    p_draft.set_defaults(func=cmd_draft)

    p_newsletter = sub.add_parser("newsletter", help="Compile a newsletter from worthy items")
    p_newsletter.add_argument("--limit", type=int, default=5)
    p_newsletter.add_argument("--title", default="Secure AI Engineering Weekly")
    p_newsletter.set_defaults(func=cmd_newsletter)

    p_daily = sub.add_parser("daily", help="Run the full daily workflow: collect -> score -> draft -> verify -> newsletter -> checkpoint")
    p_daily.add_argument("--dry-run", action="store_true", help="Collect without saving")
    p_daily.add_argument("--collect-limit", type=int, default=5)
    p_daily.add_argument("--draft-limit", type=int, default=3)
    p_daily.add_argument("--newsletter-limit", type=int, default=5)
    p_daily.add_argument("--newsletter-title", default="Secure AI Engineering Daily")
    p_daily.add_argument("--skip-reddit", action="store_true")
    p_daily.add_argument("--skip-youtube", action="store_true")
    p_daily.add_argument("--skip-instagram", action="store_true")
    p_daily.add_argument("--min-confidence", type=int, default=30)
    p_daily.add_argument("--min-signal", type=int, default=20)
    p_daily.set_defaults(func=cmd_daily)

    p_queue = sub.add_parser("queue", help="Show approval queue")
    p_queue.add_argument("--limit", type=int, default=20)
    p_queue.set_defaults(func=cmd_queue)

    p_approve = sub.add_parser("approve", help="Approve a draft by item_id")
    p_approve.add_argument("item_id")
    p_approve.set_defaults(func=cmd_approve)

    p_verify = sub.add_parser("verify", help="Verify queued drafts against quality gates")
    p_verify.add_argument("--limit", type=int, default=5)
    p_verify.add_argument("item_id", nargs="?", default=None)
    p_verify.set_defaults(func=cmd_verify)

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

    p_analyze = sub.add_parser("analyze-content", help="Run daily relevance + perfection analysis on queued drafts")
    p_analyze.add_argument("--date", default=None, help="Override date (YYYY-MM-DD) for testing")
    p_analyze.add_argument("--no-llm", action="store_true", help="Use rule-based heuristics instead of LLM")
    p_analyze.add_argument("--limit", type=int, default=10, help="Maximum drafts to analyze")
    p_analyze.set_defaults(func=cmd_analyze_content)

    p_draft_today = sub.add_parser("draft-today", help="Draft today's post using the 7-day calendar + LLM humanizer")
    p_draft_today.add_argument("--limit", type=int, default=1, help="Number of draft candidates to produce")
    p_draft_today.add_argument("--dry-run", action="store_true", help="Print draft without saving")
    p_draft_today.add_argument("--date", default=None, help="Override date (YYYY-MM-DD) for testing")
    p_draft_today.add_argument("--with-image", action="store_true", dest="with_image", help="Generate or fetch an image for the draft (OG first, then ComfyUI)")
    p_draft_today.add_argument("--force-comfy", action="store_true", dest="force_comfy", help="Always generate a fresh ComfyUI image (skips OpenGraph fallback)")
    p_draft_today.set_defaults(func=cmd_draft_today)

    p_review_dashboard = sub.add_parser("review-dashboard", help="Generate static HTML review dashboard for pending drafts")
    p_review_dashboard.set_defaults(func=cmd_review_dashboard)

    p_review_server = sub.add_parser("review-server", help="Start tiny HTTP server for the review dashboard")
    p_review_server.add_argument("--host", default="127.0.0.1", help="Bind address")
    p_review_server.add_argument("--port", type=int, default=8080, help="Port")
    p_review_server.set_defaults(func=cmd_review_server)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
