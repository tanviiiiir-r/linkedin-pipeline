"""Generate LinkedIn post + newsletter snippet from a scored item.

This module replaces the earlier rule-based drafting with a cleaner, humanized
output. It also produces derivative formats: short LinkedIn post, newsletter
section, and optional "pills" (data/forward-looking/narrative snippets).
"""
import html
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from pipeline.scoring import ScoreResult
from pipeline.storage import Item
from pipeline.topics import hashtags_from_topics


class Draft(BaseModel):
    item_id: str
    pillar: str
    title: str
    source_url: str
    created_at: str
    approved: bool = False
    published: bool = False
    linkedin_post: str = ""
    newsletter_section: str = ""
    short_pill: str = ""      # 1-2 sentence takeaway (like an infographic caption)
    forward_pill: str = ""    # "what this enables next"
    narrative_pill: str = "" # storytelling version
    hashtags: list[str] = []
    image_path: str = ""


PILLAR_HASHTAGS = {
    "tool_drop": ["#AI", "#BuilderTools", "#MachineLearning"],
    "viral_explained": ["#AI", "#TechTrends", "#Explainer"],
    "pattern_spotting": ["#AI", "#PatternSpotting", "#EmergingTech"],
    "builder_memo": ["#AI", "#BuilderMemo", "#DevTips"],
    "tomorrow_in_ai": ["#AI", "#FutureOfAI", "#ThoughtLeadership"],
}


_PILLAR_HOOKS = {
    "tool_drop": "New tool alert",
    "viral_explained": "Why this matters for AI builders",
    "pattern_spotting": "Pattern worth watching",
    "builder_memo": "Builder memo",
    "tomorrow_in_ai": "Tomorrow in AI",
}


def _clean_text(text: str) -> str:
    if not text:
        return ""
    # Unescape HTML entities
    text = html.unescape(text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    # Remove markdown link syntax but keep URL separately
    return text.strip()


def _extract_claims(item: Item) -> list[str]:
    """Return the strongest 2-3 claims from raw content."""
    candidates = []
    for line in item.raw_content.splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line) > 80 and any(
            kw in line.lower()
            for kw in [
                "released", "launched", "introduces", "announced", "new", "model",
                "agent", "vulnerability", "attack", "benchmark", "api", "tool",
                "framework", "llm", "mcp", "rag", "secure", "efficiency", "latency",
                "quant", "fine-tune", "eval", "red-team",
            ]
        ):
            candidates.append(line)
        if len(candidates) >= 3:
            break
    return candidates


def _summarize_why(item: Item) -> str:
    claims = _extract_claims(item)
    if claims:
        return claims[0]
    return item.summary or item.item_title


def _hashtags_for(pillar: str, topics: list[str]) -> list[str]:
    tags = PILLAR_HASHTAGS.get(pillar, ["#AI", "#MachineLearning"]).copy()
    for t in topics[:2]:
        clean = "".join(c for c in t if c.isalnum())
        if clean and f"#{clean.title()}" not in tags:
            tags.append(f"#{clean.title()}")
    return list(dict.fromkeys(tags))[:5]


def draft_item(item: Item, score: ScoreResult) -> Draft:
    """Create a human-sounding draft with derivative pills."""
    title = _clean_text(item.item_title)
    url = item.item_url
    why = _summarize_why(item)
    pillar = score.pillar or "general"
    hook = _PILLAR_HOOKS.get(pillar, "AI signal")

    # Use extracted topics for hashtags; fall back to pillar defaults
    tags = hashtags_from_topics(score.topics) if score.topics else _hashtags_for(pillar, item.topics)

    linkedin_post = f"""{hook}: {title}

What changed: {why[:240]}

Why builders should care: this is the kind of signal that shifts how we design, deploy, and secure AI systems. Watch it, experiment with it, and share what breaks.

Read more: {url}

{" ".join(tags)}""".strip()

    newsletter_section = f"""## {title}

**Source:** {url}
**Signal strength:** {pillar.replace('_', ' ').title()} — {score.pillar_confidence}% confidence
**Topics:** {', '.join(score.topics[:4]) if score.topics else 'general'}

**What changed:** {why[:300]}

**Builder takeaway:** {item.key_claims[0] if item.key_claims else 'Worth monitoring closely.'}

**Security / reliability angle:** {item.key_claims[1] if len(item.key_claims) > 1 else 'Consider how this behaves under misuse, scaling pressure, or adversarial input.'}

**Efficiency / cost angle:** {item.key_claims[2] if len(item.key_claims) > 2 else 'Track the implementation cost and operational overhead as it matures.'}
""".strip()

    if len(newsletter_section.split()) < 80:
        newsletter_section += (
            f"\n\n**Why this matters now:** {item.summary or title} is the kind of signal that "
            "changes how teams design, deploy, and secure AI systems. Watch it, experiment with it, "
            "and share what breaks."
        )

    short_pill = f"{title}: {why[:160]}"
    forward_pill = f"If {title.split(' ')[0]} keeps moving this fast, the next 6 months will redefine how teams ship {pillar.replace('_', ' ')} workflows."
    narrative_pill = f"A builder I follow flagged '{title}'. Here's why I paused: {why[:200]}"

    return Draft(
        item_id=item.id,
        pillar=pillar,
        title=title,
        source_url=url,
        created_at=datetime.now(timezone.utc).isoformat(),
        linkedin_post=linkedin_post,
        newsletter_section=newsletter_section,
        short_pill=short_pill,
        forward_pill=forward_pill,
        narrative_pill=narrative_pill,
        hashtags=tags,
    )


def save_draft(draft: Draft, queue_dir: Path) -> Path:
    queue_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    filename = f"{ts}--{draft.item_id}--{draft.pillar}.md"
    path = queue_dir / filename
    path.write_text(_draft_markdown(draft))
    return path


def _draft_markdown(draft: Draft) -> str:
    return f"""---
item_id: {draft.item_id}
pillar: {draft.pillar}
title: {draft.title}
source_url: {draft.source_url}
created_at: {draft.created_at}
approved: {draft.approved}
published: {draft.published}
image_path: {draft.image_path}
hashtags: {', '.join(draft.hashtags)}
---

## LinkedIn Post
{draft.linkedin_post}

## Newsletter Section
{draft.newsletter_section}

## Short Pill
{draft.short_pill}

## Forward Pill
{draft.forward_pill}

## Narrative Pill
{draft.narrative_pill}

## Actions
- [ ] Approved by human
- [ ] Published to LinkedIn
- [ ] Published to Twitter/X
"""


def load_drafts(queue_dir: Path) -> list[Draft]:
    """Load full drafts from queue markdown files."""
    drafts = []
    if not queue_dir.exists():
        return drafts
    for path in sorted(queue_dir.glob("*.md"), reverse=True):
        text = path.read_text()
        draft = _parse_draft_markdown(text)
        if draft:
            drafts.append(draft)
    return drafts


def _split_frontmatter(text: str) -> tuple[str | None, str | None]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not m:
        return None, None
    return m.group(1).strip(), m.group(2).strip()


def _parse_draft_markdown(text: str) -> Draft | None:
    frontmatter, body = _split_frontmatter(text)
    if not frontmatter:
        return None
    data: dict[str, str] = {}
    for line in frontmatter.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip()

    sections: dict[str, str] = {}
    current_heading = None
    current_lines: list[str] = []
    for line in body.splitlines():
        heading_match = re.match(r"^##\s+(.*)$", line)
        if heading_match:
            if current_heading is not None:
                sections[current_heading] = "\n".join(current_lines).strip()
            current_heading = heading_match.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_heading is not None:
        sections[current_heading] = "\n".join(current_lines).strip()

    return Draft(
        item_id=data.get("item_id", ""),
        pillar=data.get("pillar", ""),
        title=data.get("title", ""),
        source_url=data.get("source_url", ""),
        created_at=data.get("created_at", ""),
        approved=data.get("approved", "false").lower() == "true",
        published=data.get("published", "false").lower() == "true",
        image_path=data.get("image_path", ""),
        linkedin_post=sections.get("LinkedIn Post", ""),
        newsletter_section=sections.get("Newsletter Section", ""),
        short_pill=sections.get("Short Pill", ""),
        forward_pill=sections.get("Forward Pill", ""),
        narrative_pill=sections.get("Narrative Pill", ""),
        hashtags=[t.strip() for t in data.get("hashtags", "").split(",") if t.strip()],
    )


def compile_newsletter(drafts: list[Draft], title: str = "Secure AI Engineering Weekly") -> str:
    """Compile approved drafts into a single newsletter markdown document."""
    sections = [
        f"# {title}",
        f"_Compiled at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
    ]
    for d in drafts:
        sections.append(d.newsletter_section)
        sections.append("")
    return "\n".join(sections).strip()
