"""LLM-based drafting v2: humanized posts driven by DayPlan + Voice.

- Reads `DayPlan` + `Voice`.
- Calls `pipeline.llm_client.complete()`.
- Parses JSON response.
- Validates against Pydantic `Draft` schema.
- Falls back to rule-based `draft_item()` on failure.
"""
import json
import logging
import re
from datetime import datetime, timezone

from pydantic import ValidationError

from config.calendar import DayPlan, post_type_for_date
from pipeline.drafting import Draft, draft_item
from pipeline.llm_client import LLMResponse, complete, is_available
from pipeline.scoring import ScoreResult
from pipeline.storage import Item
from pipeline.voice import Voice, voice_for

try:
    from pipeline.analytics import log_post_metadata
except ImportError:  # pragma: no cover
    log_post_metadata = None


class EditorialAngle:
    """Internal editorial plan derived from the source before drafting."""

    def __init__(
        self,
        hook: str,
        core_observation: str,
        tension: str,
        editorial_angle: str,
        builder_implication: str,
        takeaway: str,
        narrative_type: str = "observation → insight",
        hook_type: str = "specific consequence",
    ):
        self.hook = hook
        self.core_observation = core_observation
        self.tension = tension
        self.editorial_angle = editorial_angle
        self.builder_implication = builder_implication
        self.takeaway = takeaway
        self.narrative_type = narrative_type
        self.hook_type = hook_type

    def to_prompt_text(self) -> str:
        return (
            f"Hook idea ({self.hook_type}): {self.hook}\n"
            f"Core observation: {self.core_observation}\n"
            f"Tension / surprising detail: {self.tension}\n"
            f"Editorial angle: {self.editorial_angle}\n"
            f"Builder implication: {self.builder_implication}\n"
            f"Takeaway / CTA seed: {self.takeaway}\n"
            f"Narrative structure: {self.narrative_type}"
        )

logger = logging.getLogger(__name__)


class DraftV2Error(Exception):
    """Raised when the LLM output cannot be parsed into a valid Draft."""


_DRAFT_JSON_KEYS = [
    "linkedin_post",
    "newsletter_section",
    "short_pill",
    "forward_pill",
    "narrative_pill",
    "hashtags",
]


def _log_metadata(draft: Draft, narrative_type: str, hook_type: str) -> None:
    if log_post_metadata is None:
        return
    try:
        log_post_metadata(
            item_id=draft.item_id,
            pillar=draft.pillar,
            narrative_type=narrative_type,
            hook_type=hook_type,
            word_count=len(draft.linkedin_post.split()),
            cta_type="question" if draft.linkedin_post.rstrip().endswith("?") else "takeaway",
            draft_version="v2",
        )
    except Exception:  # noqa: BLE001
        logger.debug("Failed to log caption metadata for %s", draft.item_id)


def _strip_code_fences(text: str) -> str:
    """Remove markdown ```json ... ``` fences if the model added them."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop first fence line (often includes 'json')
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _safe_json(text: str) -> dict:
    """Parse JSON, tolerating trailing punctuation and minor cleanup."""
    text = _strip_code_fences(text)
    # Some models emit trailing commas or explanatory text after JSON.
    # Try strict first, then a conservative regex fallback to extract the first {...} object.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError as e:
                logger.warning("JSON extraction failed: %s", e)
        raise


def _derive_editorial_angle(
    item: Item,
    score: ScoreResult,
    day_plan: DayPlan,
) -> EditorialAngle:
    """Use a cheap, focused LLM call to derive the editorial angle from the source."""
    if not is_available():
        return EditorialAngle(
            hook=item.item_title,
            core_observation=item.summary or item.item_title,
            tension="",
            editorial_angle="",
            builder_implication=day_plan.job,
            takeaway=voice_for(day_plan.post_type).cta_by_day.get(day_plan.post_type, ""),
            narrative_type="observation → insight",
            hook_type="source title",
        )

    claims = "\n".join(f"- {c}" for c in (item.key_claims or [])) or "- [No claims extracted]"
    topics = ", ".join(score.topics or item.topics or [])
    system = (
        "You are an editorial analyst for a technically credible LinkedIn creator. "
        "Read the source below and derive a short editorial angle. "
        "Never invent personal experience. Output only valid JSON with these keys: "
        "hook, core_observation, tension, editorial_angle, builder_implication, "
        "takeaway, narrative_type, hook_type. "
        "narrative_type must be one of: story -> insight, observation -> explanation, "
        "news -> interpretation, problem -> discovery -> lesson, contrarian interpretation. "
        "hook_type must be one of: surprising observation, tension/contrast, "
        "specific consequence, unusual detail, honest opinion, question, "
        "everyone is talking about X, direct lesson."
    )
    prompt = (
        f"Day plan: {day_plan.day_name} — {day_plan.post_type}: {day_plan.job}\n\n"
        f"Source title: {item.item_title}\n"
        f"Primary topic: {score.primary_topic or topics or 'general'}\n"
        f"Summary:\n{item.summary or item.raw_content[:800]}\n\n"
        f"Key claims:\n{claims}\n\n"
        "Extract the angle as JSON only."
    )
    try:
        resp = complete(prompt, system=system, temperature=0.6)
        data = _safe_json(resp.text)
        if not isinstance(data, dict):
            raise DraftV2Error("Angle response was not a JSON object")
        return EditorialAngle(
            hook=data.get("hook", item.item_title),
            core_observation=data.get("core_observation", item.summary or item.item_title),
            tension=data.get("tension", ""),
            editorial_angle=data.get("editorial_angle", ""),
            builder_implication=data.get("builder_implication", ""),
            takeaway=data.get("takeaway", ""),
            narrative_type=data.get("narrative_type", "observation → insight"),
            hook_type=data.get("hook_type", "specific consequence"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to derive editorial angle for %s: %s; using fallback", item.id, exc)
        return EditorialAngle(
            hook=item.item_title,
            core_observation=item.summary or item.item_title,
            tension="",
            editorial_angle="",
            builder_implication=day_plan.job,
            takeaway=voice_for(day_plan.post_type).cta_by_day.get(day_plan.post_type, ""),
            narrative_type="observation → insight",
            hook_type="source title",
        )


def _score_variant(text: str, source_text: str) -> dict[str, float]:
    """Rule-based scoring of one LinkedIn post variant (0-1 each)."""
    import re

    words = text.split()
    wc = len(words)
    paragraphs = [p for p in text.split("\n\n") if p.strip()]

    # Source fidelity: non-stopword overlap with source text
    stop = {
        "the", "a", "an", "is", "are", "was", "were", "this", "that", "it", "to", "of",
        "and", "in", "on", "for", "with", "as", "at", "by", "from", "or", "but", "not",
        "be", "have", "has", "had", "do", "does", "did", "will", "would", "could", "should",
        "can", "may", "might", "about", "up", "out", "if", "so", "than", "then", "them",
        "they", "their", "we", "my", "i", "you", "me", "he", "she", "his", "her", "what",
        "how", "why", "when", "where", "who", "which", "while", "because", "since", "just",
        "now", "like", "one", "two", "get", "make", "way", "more", "new", "also", "only",
        "even", "well", "still", "back", "there", "here", "too", "very", "really",
    }
    draft_words = {w.lower() for w in re.findall(r"\b\w+\b", text)} - stop
    source_words = {w.lower() for w in re.findall(r"\b\w+\b", source_text)} - stop
    fidelity = len(draft_words & source_words) / max(1, len(draft_words))

    # Specificity: numbers / concrete entities
    has_number = bool(re.search(r"\b\d+(?:\.\d+)?%?\b", text))
    has_entity = bool(re.search(r"\b(?:OpenAI|Anthropic|Google|Meta|Microsoft|NVIDIA|AWS|Cloudflare|GitHub|arXiv|Reddit|LangChain|Llama|GPT-4|Claude|Mistral|Gemini|Docker|Kubernetes|API|MCP|RAG)\b", text, re.IGNORECASE))
    specificity = 0.7 if (has_number or has_entity) else 0.4

    # Point of view: interpretation signals
    pov_signals = [
        r"\bmy read is\b", r"\bI think\b", r"\bthe interesting part is\b",
        r"\bwhat surprised me\b", r"\bthe detail I\'d watch\b", r"\bthat sounds small, but\b",
        r"\bthe obvious takeaway\b", r"\bthe more important signal\b", r"\beveryone is focusing on\b",
        r"\bI\'m more interested in\b", r"\bhonestly\b", r"\bthe weird part is\b",
        r"\bwhat caught my attention\b", r"\bfor builders\b", r"\bthe move is\b",
    ]
    pov = sum(1 for s in pov_signals if re.search(s, text, re.IGNORECASE)) / max(1, len(pov_signals))

    # Human voice: contractions, short sentences, direct address
    contractions = bool(re.search(r"\b(I\'|you\'|we\'|they\'|it\'|that\'|there\'|here\'|what\'|how\'|who\'|isn\'|aren\'|don\'|doesn\'|didn\'|won\'|wouldn\'|couldn\'|shouldn\'|haven\'|hasn\'|hadn\')", text))
    short_sentences = sum(1 for sent in re.split(r"(?<=[.!?])\s+", text) if 0 < len(sent.split()) <= 12) / max(1, len(paragraphs))
    human_voice = 0.5 + (0.25 if contractions else 0) + (0.25 * min(1.0, short_sentences))

    # Hook strength: first paragraph has a strong opener
    hook_text = paragraphs[0] if paragraphs else text[:120]
    hook_patterns = [
        r"\bjust got\b", r"\bthe part that caught\b", r"\bthe interesting part is\b",
        r"\bwhat surprised me\b", r"\beveryone is\b", r"\bI\'m less interested\b",
        r"\bthe detail I\'d watch\b", r"\?$", r"\bthe problem looked\b", r"\bthe practical shift\b",
    ]
    hook = sum(1 for h in hook_patterns if re.search(h, hook_text, re.IGNORECASE)) / max(1, len(hook_patterns))

    # Usefulness: builder implication / takeaway
    usefulness = 0.6
    if re.search(r"\bfor builders\b|\bthe move is\b|\bwhat to try\b|\btry this\b|\baudit\b|\bwatch\b", text, re.IGNORECASE):
        usefulness = 0.9

    # Naturalness: length and paragraph variety
    naturalness = 0.5
    if 50 <= wc <= 250:
        naturalness += 0.2
    if 3 <= len(paragraphs) <= 6:
        naturalness += 0.2
    if paragraphs and len({len(p.split()) for p in paragraphs}) > 1:
        naturalness += 0.1

    # Repetition penalty
    seen: set[tuple[str, ...]] = set()
    repeated = 0
    for p in paragraphs:
        words_l = [w.lower() for w in re.findall(r"\b\w+\b", p) if len(w) > 2]
        ngrams = {tuple(words_l[i:i + 4]) for i in range(max(0, len(words_l) - 3))}
        repeated += len(seen & ngrams)
        seen |= ngrams
    repetition = max(0.0, 1.0 - repeated * 0.1)

    return {
        "source_fidelity": min(1.0, fidelity),
        "specificity": specificity,
        "point_of_view": min(1.0, pov),
        "human_voice": min(1.0, human_voice),
        "hook_strength": min(1.0, hook),
        "usefulness": usefulness,
        "naturalness": naturalness,
        "repetition": repetition,
    }


def _weighted_score(scores: dict[str, float]) -> float:
    weights = {
        "source_fidelity": 0.20,
        "specificity": 0.15,
        "point_of_view": 0.15,
        "human_voice": 0.15,
        "hook_strength": 0.10,
        "usefulness": 0.10,
        "naturalness": 0.10,
        "repetition": 0.05,
    }
    return sum(scores[k] * weights[k] for k in weights)


def _build_system_prompt(voice: Voice, day_plan: DayPlan, angle: EditorialAngle) -> str:
    no_go = ", ".join(voice.no_go_words)
    max_words = voice.max_words.get(day_plan.post_type, 220)
    cta = angle.takeaway or voice.cta_by_day.get(day_plan.post_type, "")
    return (
        f"{voice.persona}\n"
        f"Tone: {', '.join(voice.tone)}.\n"
        f"Today's job ({day_plan.day_name}, {day_plan.post_type}): {day_plan.job}.\n"
        f"Narrative structure to use: {angle.narrative_type}.\n"
        "Do not force a visible template. Do not use 'Why builders should care:' or "
        "'Builder memo:' as a structural label. Do not invent personal experience.\n"
        "Write like a technically competent person talking to another smart person. "
        "Use concrete nouns and verbs, short sentences, natural contractions, and varied paragraph lengths.\n"
        "Do not explain obvious things, restate the source title, use corporate filler, motivational language, "
        "or generic transitions like 'Furthermore', 'Moreover', 'In conclusion', 'At the end of the day'.\n"
        "Do not use phrases like 'in today's rapidly evolving AI landscape', 'game changer', 'revolutionize', "
        "'leverage', or 'unlock the power of'.\n"
        f"Never use these words or phrases: {no_go}.\n"
        f"Keep the LinkedIn post under {max_words} words.\n"
        f"End with one discussion prompt or takeaway derived from the tension. Suggested: {cta}.\n"
        "Output only valid JSON with keys: linkedin_post, newsletter_section, "
        "short_pill, forward_pill, narrative_pill, hashtags.\n"
        "hashtags must be a list of 4-6 strings starting with #, chosen from the actual topic/content."
    )


def _build_user_prompt(item: Item, score: ScoreResult, day_plan: DayPlan, angle: EditorialAngle) -> str:
    claims = "\n".join(f"- {c}" for c in (item.key_claims or [])) or "- [No claims extracted]"
    topics = ", ".join(score.topics or item.topics or [])
    source_text = (
        f"Source title: {item.item_title}\n"
        f"Source URL: {item.item_url}\n"
        f"Primary topic: {score.primary_topic or topics or 'general'}\n"
        f"Confidence: {score.pillar_confidence}% | Signal strength: {score.signal_strength}%\n"
        f"Pillar: {score.pillar or day_plan.post_type}\n"
        f"Summary:\n{item.summary or item.raw_content[:800]}\n\n"
        f"Key claims:\n{claims}\n"
    )
    return (
        f"Day plan: {day_plan.day_name} — {day_plan.post_type}: {day_plan.job}\n"
        f"Day instructions: {day_plan.prompt_instructions}\n\n"
        f"{source_text}\n"
        "Before writing, extract from the source:\n"
        "1. Core event\n"
        "2. 2–4 strongest facts\n"
        "3. Most surprising detail\n"
        "4. Important limitation/caveat\n"
        "5. Who is affected\n"
        "6. Why it matters now\n"
        "7. Builder implication\n"
        "8. One defensible editorial interpretation\n\n"
        "Derived editorial angle:\n"
        f"{angle.to_prompt_text()}\n\n"
        "Now write the LinkedIn post following the angle. Do not invent first-person events. "
        "Use interpretation ('my read is', 'the interesting part is') rather than fabricated experience.\n"
        f"Preferred sources for this day: {', '.join(day_plan.source_bias)}.\n"
        "Return valid JSON only."
    )


def _hydrate_draft(
    item: Item,
    score: ScoreResult,
    data: dict,
    day_plan: DayPlan,
) -> Draft:
    """Turn parsed JSON into a Pydantic Draft, filling missing fields safely."""
    now = datetime.now(timezone.utc).isoformat()
    hashtags = data.get("hashtags") or []
    if isinstance(hashtags, str):
        hashtags = [h.strip() for h in hashtags.replace(",", " ").split() if h.strip()]
    # Normalize hashtag strings
    hashtags = [f"#{h.lstrip('#').strip()}" for h in hashtags if h.strip()]

    post = data.get("linkedin_post", "").strip()
    # Ensure source URL appears in the post body for verifier/audience
    if item.item_url and item.item_url not in post:
        post = f"{post}\n\nRead more: {item.item_url}"
    # Ensure founder_signal posts end with a question
    if day_plan.post_type == "founder_signal" and post and not post.endswith("?"):
        cta = voice_for(day_plan.post_type).cta_by_day.get("founder_signal", "Founders: what wedge would you build here?")
        if cta not in post:
            post = f"{post}\n\n{cta}"

    newsletter_section = data.get("newsletter_section", "").strip()
    # Ensure newsletter section is at least 80 words
    if len(newsletter_section.split()) < 80:
        newsletter_section += (
            f"\n\n**Why this matters now:** {item.summary or item.item_title} "
            "is the kind of signal that changes how teams design, deploy, and secure AI systems. "
            "Watch it, experiment with it in a safe environment, and share what breaks."
        )

    return Draft(
        item_id=item.id,
        pillar=day_plan.post_type,
        title=item.item_title,
        source_url=item.item_url,
        created_at=now,
        approved=False,
        published=False,
        linkedin_post=post,
        newsletter_section=newsletter_section,
        short_pill=data.get("short_pill", "").strip(),
        forward_pill=data.get("forward_pill", "").strip(),
        narrative_pill=data.get("narrative_pill", "").strip(),
        hashtags=hashtags,
        image_path=item.image_path if hasattr(item, "image_path") else "",
        image_source=item.image_source if hasattr(item, "image_source") else "",
        image_candidates=item.image_candidates if hasattr(item, "image_candidates") else [],
        image_candidate_sources=[],
        scheduled_for=item.expires_at if hasattr(item, "expires_at") else "",
    )


def draft_item_v2(
    item: Item,
    score: ScoreResult,
    day_plan: DayPlan | None = None,
) -> Draft:
    """Create a humanized Draft via LLM, with rule-based fallback.

    Args:
        item: The collected/scored item.
        score: The score result from `score_item()`.
        day_plan: Editorial plan for the target day. Defaults to today.

    Returns:
        A validated Draft. Falls back to the rule-based drafter if the LLM is
        unavailable, returns invalid JSON, or produces a schema violation.
    """
    day_plan = day_plan or post_type_for_date()
    voice = voice_for(day_plan.post_type)

    if not is_available():
        logger.info("LLM unavailable; falling back to rule-based draft for %s", item.id)
        draft = draft_item(item, score)
        _log_metadata(draft, "rule_fallback", "none")
        return draft

    angle = _derive_editorial_angle(item, score, day_plan)
    system = _build_system_prompt(voice, day_plan, angle)
    source_text = " ".join([item.item_title or "", item.summary or "", " ".join(item.key_claims or []), item.raw_content or ""])

    variants: list[tuple[str, dict[str, float], float]] = []
    for _ in range(3):
        try:
            prompt = _build_user_prompt(item, score, day_plan, angle)
            resp: LLMResponse = complete(prompt, system=system, temperature=0.8)
            if not resp.text:
                continue
            data = _safe_json(resp.text)
            missing = [k for k in _DRAFT_JSON_KEYS if k not in data]
            if missing:
                continue
            post = data.get("linkedin_post", "").strip()
            if not post:
                continue
            scores = _score_variant(post, source_text)
            total = _weighted_score(scores)
            variants.append((post, scores, total))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Variant generation failed for %s: %s", item.id, exc)

    if not variants:
        logger.warning("All LLM variants failed for %s; falling back to rule-based", item.id)
        draft = draft_item(item, score)
        _log_metadata(draft, "rule_fallback", "none")
        return draft

    # Select the best-scoring variant; tie-break to first
    variants.sort(key=lambda x: x[2], reverse=True)
    best_post, _best_scores, _ = variants[0]

    # Re-assemble the draft from the best variant, keeping other fields from the last LLM response
    try:
        final_prompt = _build_user_prompt(item, score, day_plan, angle)
        resp: LLMResponse = complete(final_prompt, system=system, temperature=0.7)
        data = _safe_json(resp.text)
        data["linkedin_post"] = best_post
    except Exception as exc:  # noqa: BLE001
        logger.warning("Final draft call failed for %s: %s; using best variant only", item.id, exc)
        data = {"linkedin_post": best_post, "newsletter_section": "", "short_pill": "", "forward_pill": "", "narrative_pill": "", "hashtags": []}

    try:
        missing = [k for k in _DRAFT_JSON_KEYS if k not in data]
        if missing:
            raise DraftV2Error(f"Missing keys in LLM output: {missing}")
        draft = _hydrate_draft(item, score, data, day_plan)
    except (json.JSONDecodeError, DraftV2Error, ValidationError, TypeError, ValueError) as e:
        logger.warning("LLM draft failed for %s: %s; falling back to rule-based", item.id, e)
        draft = draft_item(item, score)
        _log_metadata(draft, "rule_fallback", "none")
        return draft

    _log_metadata(draft, angle.narrative_type, angle.hook_type)
    return draft


def draft_for_day(
    item: Item,
    score: ScoreResult,
    for_date: datetime | None = None,
) -> Draft:
    """Convenience wrapper that resolves a calendar day and drafts for it."""
    target = for_date.date() if for_date else datetime.now(timezone.utc).date()
    day_plan = post_type_for_date(target)
    return draft_item_v2(item, score, day_plan=day_plan)
