"""L4-style pre-publish verifier for drafted LinkedIn posts and newsletter sections.

Implements a rule-based checker (no LLM cost) that judges a draft against the
pipeline's tone, taxonomy, and anti-slop rules. Returns an APPROVE / REJECT /
UNCERTAIN verdict with reasoning.
"""
import re
from enum import Enum

from pydantic import BaseModel

from config.calendar import day_plan
from pipeline.drafting import Draft
from pipeline.storage import Item
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


def _has_specific_topics(hashtags: list[str], topics: list[str], day_plan_hashtags: list[str] | None = None) -> bool:
    """Return True if at least one hashtag maps to the taxonomy or day plan."""
    taxonomy = _all_taxonomy_topics()
    day_plan_set = {h.lstrip("#").lower().replace("-", "") for h in (day_plan_hashtags or [])}
    for h in hashtags:
        clean = h.lstrip("#").lower().replace("-", "")
        if clean in day_plan_set:
            return True
        for t in taxonomy:
            if clean == t.lower().replace("-", ""):
                return True
    for t in topics:
        if t in taxonomy:
            return True
    return False






# --- Human voice / storytelling upgrade helpers --------------------------------
_TEMPLATE_PHRASES = [
    r"Why builders should care",
    r"this is the kind of signal that shifts how we design, deploy, and secure AI systems",
    r"Watch it, experiment with it, and share what breaks",
    r"Builder memo:",
    r"What changed:",
]

_GENERIC_PATTERNS = [
    r"game[- ]?changer",
    r"revolutionary",
    r"revolutionize",
    r"disruptive",
    r"paradigm shift",
    r"cutting[- ]edge",
    r"next[- ]gen",
    r"transformative",
    r"unleash",
    r"leverage",
    r"unlock",
    r"synergy",
    r"thought leader",
    r"deep dive",
    r"ecosystem",
]

_FABRICATED_FIRST_PERSON = [
    r"\bI tested\b",
    r"\bI built\b",
    r"\bI spent the weekend\b",
    r"\bI discovered\b",
    r"\bI talked to\b",
    r"\bI deployed\b",
    r"\bI shipped\b",
    r"\bmy team\b",
    r"\bwe deployed\b",
    r"\bwe shipped\b",
    r"\bwe built\b",
    r"\bIn my experience\b",
    r"\bI keep seeing\b",
]

_POV_SIGNALS = [
    r"\bmy read is\b",
    r"\bI think\b",
    r"\bI disagree\b",
    r"\bI'm less interested in\b",
    r"\bthe interesting part is\b",
    r"\bwhat surprised me\b",
    r"\bthe detail I'd watch\b",
    r"\bthat sounds small, but\b",
    r"\bthe obvious takeaway\b",
    r"\bthe more important signal\b",
    r"\beveryone is focusing on\b",
    r"\bI'm more interested in\b",
    r"\bhere's where I disagree\b",
    r"\bhonestly\b",
    r"\bthe weird part is\b",
    r"\bwhat caught my attention\b",
]

_TRANSITION_WORDS = [
    "but", "yet", "instead", "actually", "so", "then", "because", "which means",
    "that's why", "here's the part", "the surprising part", "the practical shift",
]


def _has_template_phrases(text: str) -> bool:
    lower = text.lower()
    for p in _TEMPLATE_PHRASES:
        if re.search(p, lower, re.IGNORECASE):
            return True
    return False


def _count_generic_patterns(text: str) -> int:
    return sum(1 for p in _GENERIC_PATTERNS if re.search(p, text, re.IGNORECASE))


def _has_fabricated_experience(text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in _FABRICATED_FIRST_PERSON)


def _has_point_of_view(text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in _POV_SIGNALS)


def _has_specificity(text: str) -> bool:
    if re.search(r"\b\d+(?:\.\d+)?%?\b", text):
        return True
    return bool(re.search(r"\b(?:OpenAI|Anthropic|Google|Meta|Microsoft|Amazon|NVIDIA|AWS|Cloudflare|GitHub|arXiv|Reddit|Hacker News|LangChain|Llama|GPT-4|Claude|Mistral|Gemini|Pytorch|TensorFlow|Kubernetes|Docker|API|SDK|MCP|agent|prompt injection|jailbreak|RAG|fine-tune|LoRA|quantization|latency|cost)\b", text, re.IGNORECASE))


def _has_narrative_flow(text: str) -> bool:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(paragraphs) < 2:
        return False
    lower = text.lower()
    return any(t in lower for t in _TRANSITION_WORDS)


def _has_repetition(text: str) -> bool:
    """Detect repeated phrases across paragraphs; ignore source URL and short lines."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(paragraphs) < 2:
        return False
    seen: set[tuple[str, ...]] = set()
    for p in paragraphs:
        # Drop URLs and markdown headings; they repeat source URL naturally
        cleaned = re.sub(r"https?://\S+|^#+\s*|\*\*[^*]+\*\*:\s*", "", p).strip()
        if not cleaned:
            continue
        words = [w.lower() for w in re.findall(r"\b\w+\b", cleaned) if len(w) > 2]
        if len(words) < 8:
            continue
        ngrams = {tuple(words[i:i + 4]) for i in range(len(words) - 3)}
        dup = seen & ngrams
        if len(dup) >= 2:
            return True
        seen |= ngrams
    return False


def _source_grounding_score(draft: Draft, item: Item | None) -> float:
    if item is None:
        return 0.5
    source = " ".join(
        [
            item.item_title or "",
            item.summary or "",
            " ".join(item.key_claims or []),
            item.raw_content or "",
        ]
    )
    if not source.strip():
        return 0.5
    draft_text = " ".join(
        [
            draft.linkedin_post or "",
            draft.newsletter_section or "",
            draft.short_pill or "",
            draft.forward_pill or "",
            draft.narrative_pill or "",
        ]
    )
    draft_words = set(re.findall(r"\b\w+\b", draft_text.lower()))
    source_words = set(re.findall(r"\b\w+\b", source.lower()))
    if not draft_words:
        return 0.0
    stop = {
        "the", "a", "an", "is", "are", "was", "were", "this", "that", "it", "to", "of",
        "and", "in", "on", "for", "with", "as", "at", "by", "from", "or", "but", "not",
        "be", "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "can", "may", "might", "about", "up", "out", "if", "so", "than", "then",
        "them", "they", "their", "we", "my", "i", "you", "me", "read", "more", "http",
        "https", "com", "www", "ai", "new", "just", "now", "like", "one", "two", "get",
        "make", "way", "what", "how", "why", "when", "where", "who",
    }
    meaningful = draft_words - stop
    if not meaningful:
        return 0.0
    overlap = meaningful & source_words
    return len(overlap) / len(meaningful)

def _extract_claims_from_draft(text: str) -> list[str]:
    """Pull likely factual claims out of a draft for verification."""
    claims = []
    # Sentence split, keep ones with numbers, quotes, or strong assertion verbs
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        s = sentence.strip()
        if len(s) < 20:
            continue
        # Skip sentences that are mostly a CTA/link line
        if re.search(r"^Read more[: ]", s, re.IGNORECASE) or s.startswith("http"):
            continue
        has_number = re.search(r"(?<!://)\b\d+(?:%|x|\s+(?:percent|times|fold|months?|years?|days?))?\b", s)
        has_assertion = re.search(r"\b(says|showed|found|reported|claims|announced|launched|released|builds|uses|built)\b", s, re.IGNORECASE)
        has_entity = len(claims) < 3 and re.search(r"\b(Pinterest|Google|OpenAI|Anthropic|Meta|Microsoft|NVIDIA|AWS|Cloudflare|GitHub|arXiv|Reddit|YouTube)\b", s, re.IGNORECASE)
        if has_number or has_assertion or has_entity:
            claims.append(s)
        if len(claims) >= 8:
            break
    return claims


def _claim_source_overlap(claim: str, source_text: str) -> float:
    """Return Jaccard-ish word overlap between a claim and source text."""
    claim_words = set(re.findall(r"\b\w+\b", claim.lower()))
    source_words = set(re.findall(r"\b\w+\b", source_text.lower()))
    if not claim_words:
        return 0.0
    overlap = claim_words & source_words
    return len(overlap) / len(claim_words)


def _verify_claims(draft: Draft, item: Item) -> dict[str, bool]:
    """Rule-based claim verification against the original source item."""
    source_text = " ".join(
        [
            item.item_title or "",
            item.summary or "",
            " ".join(item.key_claims or []),
            item.raw_content or "",
        ]
    )
    if not source_text.strip():
        return {"claims_verified": False, "claims_source_match": False, "no_hallucinated_numbers": False}

    text = f"{draft.linkedin_post}\n{draft.newsletter_section}"
    claims = _extract_claims_from_draft(text)
    if not claims:
        # No strong factual claims = nothing to verify; pass cautiously
        return {"claims_verified": True, "claims_source_match": True, "no_hallucinated_numbers": True}

    matched = 0
    hallucinated_numbers = 0
    for claim in claims:
        overlap = _claim_source_overlap(claim, source_text)
        if overlap >= 0.35:
            matched += 1
        # Flag numbers in draft that don't appear in source at all
        numbers = re.findall(r"\b\d+(?:\.\d+)?%?\b", claim)
        source_numbers = set(re.findall(r"\b\d+(?:\.\d+)?%?\b", source_text))
        for n in numbers:
            if n not in source_numbers and not _number_tolerated(n, source_text):
                hallucinated_numbers += 1

    total = len(claims)
    match_ratio = matched / total
    checks = {
        "claims_verified": True,
        "claims_source_match": match_ratio >= 0.6,
        "no_hallucinated_numbers": hallucinated_numbers == 0,
    }
    return checks


def _number_tolerated(number: str, source_text: str) -> bool:
    """Allow small integers (1, 2, 3, 6 months) and years if they are reasonable."""
    try:
        val = int(number.rstrip("%"))
    except ValueError:
        return False
    if val in {1, 2, 3, 4, 5, 6, 12, 24, 52}:
        return True
    # Year between 2020-2030 acceptable
    return 2020 <= val <= 2030


def verify_draft(draft: Draft, item: Item | None = None) -> VerifyResult:
    """Verify a draft against pipeline quality rules."""
    text = f"{draft.linkedin_post}\n{draft.newsletter_section}\n{draft.short_pill}\n{draft.forward_pill}\n{draft.narrative_pill}"

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

    # 6. Has specific taxonomy topic (or matches today's editorial hashtag set)
    today_hashtags = day_plan().hashtag_set
    checks["has_taxonomy_topic"] = _has_specific_topics(draft.hashtags, [], today_hashtags)
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

    # 9. Claim verification (requires original item; loaded from storage)
    try:
        from pipeline.storage import load_item
        item = load_item(draft.source_url)
        if item:
            claim_checks = _verify_claims(draft, item)
            checks.update(claim_checks)
            if not claim_checks["claims_source_match"]:
                score -= 15
                reasons.append("Draft claims have low overlap with source text")
            if not claim_checks["no_hallucinated_numbers"]:
                score -= 15
                reasons.append("Draft contains numbers not found in source")
        else:
            checks["claims_verified"] = False
            checks["claims_source_match"] = False
            checks["no_hallucinated_numbers"] = False
            score -= 10
            reasons.append("Could not load source item for claim verification")
    except (RuntimeError, ValueError, TypeError):
        checks["claims_verified"] = False
        checks["claims_source_match"] = False
        checks["no_hallucinated_numbers"] = False
        score -= 5
        reasons.append("Claim verification check failed")

    # 10. Human voice / storytelling checks
    checks["not_generic_template"] = not _has_template_phrases(text)
    if not checks["not_generic_template"]:
        score -= 15
        reasons.append("Post uses a generic template phrase such as 'Why builders should care'")

    checks["low_genericness"] = _count_generic_patterns(text) == 0
    if not checks["low_genericness"]:
        score -= 10
        reasons.append("Generic hype words detected (e.g., revolutionary, game-changer)")

    checks["has_point_of_view"] = _has_point_of_view(text)
    if not checks["has_point_of_view"]:
        score -= 10
        reasons.append("Missing point of view or interpretation; reads like a summary")

    checks["has_specificity"] = _has_specificity(text)
    if not checks["has_specificity"]:
        score -= 10
        reasons.append("Draft lacks specific source-grounded details")

    checks["has_narrative_flow"] = _has_narrative_flow(text)
    if not checks["has_narrative_flow"]:
        score -= 6
        reasons.append("Narrative flow is weak; add story-like progression")

    checks["not_repetitive"] = not _has_repetition(text)
    if not checks["not_repetitive"]:
        score -= 8
        reasons.append("Repetition detected across paragraphs")

    checks["no_fabricated_experience"] = not _has_fabricated_experience(text)
    if not checks["no_fabricated_experience"]:
        score -= 20
        reasons.append("Fabricated first-person experience detected; remove claims like 'I tested' or 'my team' unless verified")

    if item is None:
        try:
            from pipeline.storage import load_item
            item = load_item(draft.source_url)
        except (RuntimeError, ValueError, TypeError, FileNotFoundError, OSError):
            item = None
    checks["source_grounded"] = _source_grounding_score(draft, item) >= 0.25
    if not checks["source_grounded"]:
        score -= 12
        reasons.append("Draft is weakly grounded in the source text")

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
