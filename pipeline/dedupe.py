"""Deduplication helpers for collected items.

Layered strategy:
1. Canonical URL normalization + exact URL hash.
2. Normalized title match.
3. Jaccard similarity over extracted keywords.
4. Optional: semantic similarity via embeddings (placeholder).
"""
import re

from pipeline.storage import Item


def canonical_url(url: str) -> str:
    """Normalize URL for dedupe: lowercase, remove tracking params, trailing slash."""
    url = url.lower().strip().rstrip("/")
    for param in ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "fbclid", "ref"]:
        url = re.sub(rf"[?\u0026]{param}=[^\u0026]*", "", url, flags=re.IGNORECASE)
    url = url.replace("?", "").replace("\u0026", "")
    return url


def normalize_title(title: str) -> str:
    """Strip punctuation, lowercase, collapse whitespace."""
    title = re.sub(r"[^\w\s]", "", title.lower())
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"^(show hn|ask hn|tell hn)\s*", "", title)
    return title


def _keyword_set(text: str) -> set[str]:
    """Extract meaningful words from text."""
    text = re.sub(r"[^\w\s]", " ", text.lower())
    words = [w for w in text.split() if len(w) > 2]
    stop = {
        "the", "and", "for", "with", "from", "this", "that", "has", "had",
        "will", "would", "could", "should", "may", "might", "can", "you",
        "your", "are", "was", "were", "been", "have", "but", "not",
        "they", "them", "their", "our", "new", "more", "about", "into",
        "after", "before", "during", "over", "under", "again", "further",
    }
    return {w for w in words if w not in stop}


def jaccard_similarity(a: str, b: str) -> float:
    """Compute Jaccard similarity over keyword sets."""
    set_a = _keyword_set(a)
    set_b = _keyword_set(b)
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def title_similarity(title_a: str, title_b: str) -> float:
    """Compare normalized titles."""
    na = normalize_title(title_a)
    nb = normalize_title(title_b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return jaccard_similarity(title_a, title_b)


def content_similarity(item_a: Item, item_b: Item) -> float:
    """Combined similarity score."""
    title_sim = title_similarity(item_a.item_title, item_b.item_title)

    text_a = " ".join([item_a.item_title, item_a.summary, *item_a.key_claims, item_a.raw_content])
    text_b = " ".join([item_b.item_title, item_b.summary, *item_b.key_claims, item_b.raw_content])
    body_sim = jaccard_similarity(text_a, text_b)

    url_bonus = 0.0
    if canonical_url(item_a.item_url) == canonical_url(item_b.item_url):
        url_bonus = 1.0

    # Boost if both share strong topic overlap
    topic_bonus = 0.0
    if hasattr(item_a, "topics") and hasattr(item_b, "topics"):
        common = set(item_a.topics or []) & set(item_b.topics or [])
        if common:
            topic_bonus = min(len(common) * 0.15, 0.35)

    return min(1.0, max(title_sim, body_sim, url_bonus) + topic_bonus)


def is_duplicate(item_a: Item, item_b: Item, title_threshold: float = 0.85, content_threshold: float = 0.60) -> bool:
    """Return True if item_b is considered a duplicate of item_a."""
    if canonical_url(item_a.item_url) == canonical_url(item_b.item_url):
        return True

    title_sim = title_similarity(item_a.item_title, item_b.item_title)
    if title_sim >= 0.95:
        return True

    body_sim = content_similarity(item_a, item_b)
    if title_sim >= title_threshold and body_sim >= content_threshold:
        return True
    return body_sim >= 0.85


def find_duplicate(item: Item, candidates: list[Item]) -> Item | None:
    """Return first candidate that is a duplicate of item."""
    for candidate in candidates:
        if candidate.item_url == item.item_url:
            continue
        if is_duplicate(item, candidate):
            return candidate
    return None


if __name__ == "__main__":
    a = Item(
        source_name="HN",
        source_url="https://news.ycombinator.com",
        item_url="https://example.com/1",
        item_title="OpenAI releases new reasoning model",
        source_type="rss",
        content_type="article",
        summary="New o3 model announced.",
        key_claims=["o3 model"],
        raw_content="",
    )
    b = Item(
        source_name="Reddit",
        source_url="https://reddit.com",
        item_url="https://reddit.com/r/ai/comments/x",
        item_title="OpenAI's new reasoning model o3",
        source_type="reddit",
        content_type="discussion",
        summary="Discussion about o3.",
        key_claims=["o3"],
        raw_content="",
    )
    print("title sim:", title_similarity(a.item_title, b.item_title))
    print("content sim:", content_similarity(a, b))
    print("is duplicate:", is_duplicate(a, b))
