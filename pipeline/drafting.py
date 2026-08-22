"""Generate LinkedIn post + optional newsletter snippet from a scored item."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from typing import Optional

from pydantic import BaseModel

from pipeline.scoring import ScoreResult
from pipeline.storage import Item


class Draft(BaseModel):
    item_id: str
    pillar: str
    linkedin_post: str
    newsletter_section: str
    hashtags: list[str]
    source_url: str
    created_at: str
    approved: bool = False
    published: bool = False


def draft_item(item: Item, score: ScoreResult) -> Draft:
    """Rule-based draft. Hermes can later replace this with LLM-driven drafting."""
    title = item.item_title.strip()
    url = item.item_url

    hooks = {
        "tool_drop": f"New tool alert: {title}",
        "viral_explained": f"Everyone is talking about {title} — here's why it matters for builders.",
        "pattern_spotting": f"I'm seeing a pattern: {title} is part of a bigger shift.",
        "builder_memo": f"Builder memo: {title}",
        "tomorrow_in_ai": f"One question {title} made me ask about the future of AI building.",
    }
    hook = hooks.get(score.pillar, title)

    hashtags = _hashtags_for(score.pillar, item.topics)

    linkedin_post = f"""{hook}

{score.reason}

What happened: {item.summary[:200] if item.summary else title}

Why it matters for AI builders: {item.key_claims[0] if item.key_claims else "See the source below."}

Takeaway: watch this signal and experiment early.

{url}

{" ".join(hashtags)}"""

    newsletter_section = f"""## {title}
**Source:** {url}
**Signal:** {score.reason}
**Builder takeaway:** {item.key_claims[0] if item.key_claims else "Worth monitoring."}
**Quote:** “{item.summary[:240] if item.summary else title}”
"""

    return Draft(
        item_id=item.id,
        pillar=score.pillar or "general",
        linkedin_post=linkedin_post.strip(),
        newsletter_section=newsletter_section.strip(),
        hashtags=hashtags,
        source_url=url,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _hashtags_for(pillar: str, topics: list[str]) -> list[str]:
    base = {
        "tool_drop": ["#AI", "#BuilderTools", "#MachineLearning"],
        "viral_explained": ["#AI", "#TechTrends", "#Explainer"],
        "pattern_spotting": ["#AI", "#PatternSpotting", "#EmergingTech"],
        "builder_memo": ["#AI", "#BuilderMemo", "#DevTips"],
        "tomorrow_in_ai": ["#AI", "#FutureOfAI", "#ThoughtLeadership"],
    }
    tags = base.get(pillar, ["#AI", "#MachineLearning"]).copy()
    for t in topics[:2]:
        clean = "".join(c for c in t if c.isalnum())
        if clean:
            tags.append(f"#{clean.title()}")
    return list(dict.fromkeys(tags))[:5]


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
source_url: {draft.source_url}
created_at: {draft.created_at}
approved: {draft.approved}
published: {draft.published}
hashtags: {', '.join(draft.hashtags)}
---

## LinkedIn Post
{draft.linkedin_post}

## Newsletter Section
{draft.newsletter_section}

## Actions
- [ ] Approved by human
- [ ] Published to LinkedIn
"""


def load_drafts(queue_dir: Path) -> list[Draft]:
    """Load full drafts from queue markdown files, preserving post body."""
    drafts = []
    if not queue_dir.exists():
        return drafts
    for path in sorted(queue_dir.glob("*.md"), reverse=True):
        text = path.read_text()
        draft = _parse_draft_markdown(text)
        if draft:
            drafts.append(draft)
    return drafts


def _split_frontmatter(text: str) -> tuple[Optional[str], Optional[str]]:
    """Return (frontmatter, body) for a YAML --- delimited markdown file."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not m:
        return None, None
    return m.group(1).strip(), m.group(2).strip()


def _parse_draft_markdown(text: str) -> Optional[Draft]:
    """Parse frontmatter + body sections into a Draft object."""
    frontmatter, body = _split_frontmatter(text)
    if not frontmatter:
        return None
    data: dict[str, str] = {}
    for line in frontmatter.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip()

    # Extract sections from body
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
        source_url=data.get("source_url", ""),
        created_at=data.get("created_at", ""),
        approved=data.get("approved", "false").lower() == "true",
        published=data.get("published", "false").lower() == "true",
        linkedin_post=sections.get("LinkedIn Post", ""),
        newsletter_section=sections.get("Newsletter Section", ""),
        hashtags=[t.strip() for t in data.get("hashtags", "").split(",") if t.strip()],
    )
