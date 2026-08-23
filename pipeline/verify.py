"""L4-style pre-publish verifier for drafted LinkedIn posts and newsletter sections.

Implements a rule-based checker (no LLM cost) that judges a draft against the
pipeline's tone, taxonomy, and anti-slop rules. Returns an APPROVE / REJECT /
UNCERTAIN verdict with reasoning.
"""
import re
from enum import Enum

from pydantic import BaseModel

from pipeline.drafting import Draft
from pipeline.topics import TAXONOMY


class Verdict(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    UNCERTAIN = "UNCERTAIN"


class VerifyResult(BaseModel):
    verdict: Verdict
    score: int  # 0-100
    checks: dict[str, bool]
    reasons: list[str]


# Patterns that make content sound AI-generated or low-value
_AI_SOUNDING_PATTERNS = [
    r"\bin the ever-evolving landscape\b",
    r"\bin today's fast-paced world\b",
    r"\bunleash the power of\b",
    r"\brevolutionize\s+(?:the\s+)?(?:industry|world|space)\b",
    r"\bgame-changer\b",
    r"\bseamless(?:ly)?\b",
    r"\bleverage\b",
    r"\bunlock\s+(?:the\s+)?potential\b",
    r"\bpowered by AI\b",
    r"\bAI-driven\b",
    r"\bdeep dive\b",
    r"\bthought leadership\b",
    r"\bkey takeaways?\b",
    r"\bnavigate the complexities\b",
    r"\bIt is important to note\b",
    r"\bIn conclusion\b",
    r"\bFurthermore\b",
    r"\bMoreover\b",
]

# Generic filler hashtags we want to avoid
_GENERIC_TAGS = {"#ai", "#machinelearning", "#technology", "#tech", "#innovation", "#future"}

# Scoring thresholds
APPROVE_MIN = 80
UNCERTAIN_MIN = 55


def _count_ai_sounding_phrases(text: str) -> int:
    return sum(1 for p in _AI_SOUNDING_PATTERNS if re.search(p, text, re.IGNORECASE))


def _all_taxonomy_topics() -> set[str]:
    topics: set[str] = set()
    for bucket in TAXONOMY.values():
        topics.update(bucket)
    return topics


def _has_specific_topics(hashtags: list[str], topics: list[str]) -> bool:
    """Return True if at least one hashtag maps to the taxonomy."""
    taxonomy = _all_taxonomy_topics()
    for h in hashtags:
        clean = h.lstrip("#").lower().replace("-", "")
        for t in taxonomy:
            if clean == t.lower().replace("-", ""):
                return True
    for t in topics:
        if t in taxonomy:
            return True
    return False


def verify_draft(draft: Draft) -> VerifyResult:
    """Verify a draft against pipeline quality rules."""
    text = "\n".join([
        draft.linkedin_post,
        draft.newsletter_section,
        draft.short_pill,
        draft.forward_pill,
        draft.narrative_pill,
    ])

    checks: dict[str, bool] = {}
    reasons: list[str] = []
    score = 100

    # 1. Length checks
    linkedin_words = len(draft.linkedin_post.split())
    checks["linkedin_length_ok"] = 50 <= linkedin_words <= 250
    if not checks["linkedin_length_ok"]:
        score -= 15
        reasons.append(f"LinkedIn post length {linkedin_words} words; target 50–250")

    # 2. AI-sounding language
    ai_count = _count_ai_sounding_phrases(text)
    checks["not_ai_sounding"] = ai_count == 0
    if not checks["not_ai_sounding"]:
        score -= ai_count * 12
        reasons.append(f"{ai_count} AI-sounding phrase(s) detected")

    # 3. Hashtag specificity
    hashtags_lower = {h.lower() for h in draft.hashtags}
    checks["hashtags_specific"] = not hashtags_lower.issubset(_GENERIC_TAGS)
    if not checks["hashtags_specific"]:
        score -= 12
        reasons.append("Hashtags are all generic; add taxonomy-specific tags")

    # 4. Link present
    checks["link_present"] = bool(draft.source_url and draft.source_url in draft.linkedin_post)
    if not checks["link_present"]:
        score -= 10
        reasons.append("Source URL missing from LinkedIn post")

    # 5. No leaked internal scoring text
    checks["no_internal_leak"] = not any(
        leak in text.lower()
        for leak in ["matched pillar", "pillar_confidence", "signal_strength", "score_item"]
    )
    if not checks["no_internal_leak"]:
        score -= 15
        reasons.append("Internal scoring language leaked into draft")

    # 6. Has specific taxonomy topic
    checks["has_taxonomy_topic"] = _has_specific_topics(draft.hashtags, [])
    if not checks["has_taxonomy_topic"]:
        score -= 8
        reasons.append("No taxonomy-specific topic detected in hashtags")

    # 7. Newsletter populated
    newsletter_words = len(draft.newsletter_section.split())
    checks["newsletter_populated"] = newsletter_words >= 80
    if not checks["newsletter_populated"]:
        score -= 8
        reasons.append("Newsletter section looks too thin")

    # 8. Title not clickbait/question-only
    title_lower = draft.title.lower()
    checks["title_substantive"] = not (
        draft.title.endswith("?") and len(draft.title.split()) < 6
    ) and not any(w in title_lower for w in ["shocking", "insane", "must watch", "you won"])
    if not checks["title_substantive"]:
        score -= 10
        reasons.append("Title looks clickbait or too vague")

    score = max(0, min(100, score))

    if score >= APPROVE_MIN:
        verdict = Verdict.APPROVE
    elif score >= UNCERTAIN_MIN:
        verdict = Verdict.UNCERTAIN
    else:
        verdict = Verdict.REJECT

    if verdict == Verdict.APPROVE:
        reasons.insert(0, "Draft meets tone, taxonomy, and anti-slop criteria")
    elif verdict == Verdict.UNCERTAIN:
        reasons.insert(0, "Draft is acceptable but has minor issues")
    else:
        reasons.insert(0, "Draft fails quality gates")

    return VerifyResult(verdict=verdict, score=score, checks=checks, reasons=reasons)


def format_verdict(result: VerifyResult) -> str:
    lines = [
        f"Verdict: {result.verdict.value} (score {result.score}/100)",
        "",
        "Checks:",
    ]
    for name, passed in result.checks.items():
        lines.append(f"  [{'x' if passed else ' '}] {name}")
    lines.append("")
    lines.append("Reasoning:")
    for r in result.reasons:
        lines.append(f"  - {r}")
    return "\n".join(lines)


if __name__ == "__main__":
    from datetime import datetime, timezone

    from pipeline.drafting import Draft

    sample = Draft(
        item_id="test123",
        pillar="builder_memo",
        title="How LLM agents leak secrets through tool use",
        source_url="https://example.com/agent-tool-leak",
        created_at=datetime.now(timezone.utc).isoformat(),
        linkedin_post="""Builder memo: How LLM agents leak secrets through tool use

What changed: A new paper shows that indirect prompt injection can exfiltrate data when an agent calls a compromised tool.

Why builders should care: this is the kind of signal that shifts how we design, deploy, and secure AI systems. Watch it, experiment with it, and share what breaks.

Read more: https://example.com/agent-tool-leak

#AgentSecurity #ToolUse #PromptInjection #SecureAI""",
        newsletter_section="## How LLM agents leak secrets through tool use\n\n**Source:** https://example.com/agent-tool-leak\n**Signal strength:** Builder Memo — 80% confidence\n**Topics:** agent-security, tool-use, prompt-injection\n\n**What changed:** A new paper shows that indirect prompt injection can exfiltrate data when an agent calls a compromised tool.\n\n**Builder takeaway:** Audit every tool your agent can call and assume the prompt context is hostile.\n\n**Security / reliability angle:** Add timeouts, output validation, and least-privilege scopes to agent tool calls.\n\n**Efficiency / cost angle:** Cheap sanity checks now prevent expensive incidents later.",
        short_pill="Agent tool leaks are the next XSS — verify every call.",
        forward_pill="If tool-use agents become standard, this attack surface defines the next 6 months of AI security work.",
        narrative_pill="A builder I follow flagged the agent tool leak paper. Here's why I paused: it maps cleanly onto every API an agent touches.",
        hashtags=["#AgentSecurity", "#ToolUse", "#PromptInjection", "#SecureAI"],
    )
    res = verify_draft(sample)
    print(format_verdict(res))
