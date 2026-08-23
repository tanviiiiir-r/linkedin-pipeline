"""LLM-based drafting v2: humanized posts driven by DayPlan + Voice.

- Reads `DayPlan` + `Voice`.
- Calls `pipeline.llm_client.complete()`.
- Parses JSON response.
- Validates against Pydantic `Draft` schema.
- Falls back to rule-based `draft_item()` on failure.
- Optionally attaches an image via `pipeline.image_engine`.
"""
import json
import logging
import re
from datetime import datetime, timezone

from pydantic import ValidationError

from config.calendar import DayPlan, post_type_for_date
from pipeline.drafting import Draft, draft_item
from pipeline.image_engine import build_image_prompt, image_for_post
from pipeline.llm_client import LLMResponse, complete, is_available
from pipeline.scoring import ScoreResult
from pipeline.storage import Item
from pipeline.voice import Voice, voice_for

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


def _build_system_prompt(voice: Voice, day_plan: DayPlan) -> str:
    no_go = ", ".join(voice.no_go_words)
    max_words = voice.max_words.get(day_plan.post_type, 220)
    cta = voice.cta_by_day.get(day_plan.post_type, "")
    return (
        f"{voice.persona}\n"
        f"Tone: {', '.join(voice.tone)}.\n"
        f"Today's job ({day_plan.day_name}, {day_plan.post_type}): {day_plan.job}.\n"
        f"Never use these words or phrases: {no_go}.\n"
        f"Keep the LinkedIn post under {max_words} words.\n"
        f"End with this discussion prompt or a natural variant of it: {cta}.\n"
        "Output only valid JSON with keys: linkedin_post, newsletter_section, "
        "short_pill, forward_pill, narrative_pill, hashtags.\n"
        "hashtags must be a list of strings starting with #."
    )


def _build_user_prompt(item: Item, score: ScoreResult, day_plan: DayPlan) -> str:
    claims = "\n".join(f"- {c}" for c in (item.key_claims or [])) or "- [No claims extracted]"
    topics = ", ".join(score.topics or item.topics or [])
    return (
        f"Day plan: {day_plan.day_name} — {day_plan.post_type}: {day_plan.job}\n\n"
        f"Source title: {item.item_title}\n"
        f"Source URL: {item.item_url}\n"
        f"Primary topic: {score.primary_topic or topics or 'general'}\n"
        f"Confidence: {score.pillar_confidence}% | Signal strength: {score.signal_strength}%\n"
        f"Pillar: {score.pillar or day_plan.post_type}\n"
        f"Summary:\n{item.summary or item.raw_content[:800]}\n\n"
        f"Key claims:\n{claims}\n\n"
        f"Preferred sources for this day: {', '.join(day_plan.source_bias)}.\n"
        "Draft the post and return valid JSON only."
    )


def _hydrate_draft(
    item: Item,
    score: ScoreResult,
    data: dict,
    day_plan: DayPlan,
    image_path: str = "",
) -> Draft:
    """Turn parsed JSON into a Pydantic Draft, filling missing fields safely."""
    now = datetime.now(timezone.utc).isoformat()
    hashtags = data.get("hashtags") or []
    if isinstance(hashtags, str):
        hashtags = [h.strip() for h in hashtags.replace(",", " ").split() if h.strip()]
    # Normalize hashtag strings
    hashtags = [f"#{h.lstrip('#').strip()}" for h in hashtags if h.strip()]

    post = data.get("linkedin_post", "").strip()
    if day_plan.post_type == "founder_signal" and post and not post.endswith("?"):
        cta = voice_for(day_plan.post_type).cta_by_day.get(
            "founder_signal", "Founders: what wedge would you build here?"
        )
        post = f"{post}\n\n{cta}"

    return Draft(
        item_id=item.id,
        pillar=day_plan.post_type,
        title=item.item_title,
        source_url=item.item_url,
        created_at=now,
        approved=False,
        published=False,
        linkedin_post=post,
        newsletter_section=data.get("newsletter_section", "").strip(),
        short_pill=data.get("short_pill", "").strip(),
        forward_pill=data.get("forward_pill", "").strip(),
        narrative_pill=data.get("narrative_pill", "").strip(),
        hashtags=hashtags,
        image_path=image_path,
    )


def draft_item_v2(
    item: Item,
    score: ScoreResult,
    day_plan: DayPlan | None = None,
    with_image: bool = False,
    prefer_source_image: bool = True,
) -> Draft:
    """Create a humanized Draft via LLM, with rule-based fallback.

    Args:
        item: The collected/scored item.
        score: The score result from `score_item()`.
        day_plan: Editorial plan for the target day. Defaults to today.
        with_image: If True, attempt to attach an image.
        prefer_source_image: Prefer OpenGraph image over ComfyUI generation.

    Returns:
        A validated Draft. Falls back to the rule-based drafter if the LLM is
        unavailable, returns invalid JSON, or produces a schema violation.
    """
    day_plan = day_plan or post_type_for_date()

    image_path = ""
    if with_image:
        try:
            img = image_for_post(
                item.item_url,
                build_image_prompt(day_plan.post_type, item.item_title, item.summary or ""),
                prefer_source_image=prefer_source_image,
            )
            if img:
                image_path = str(img)
        except Exception:
            logger.exception("Image attachment failed for %s", item.id)

    voice = voice_for(day_plan.post_type)

    if not is_available():
        logger.info("LLM unavailable; falling back to rule-based draft for %s", item.id)
        draft = draft_item(item, score)
        draft.image_path = image_path
        return draft

    system = _build_system_prompt(voice, day_plan)
    prompt = _build_user_prompt(item, score, day_plan)

    try:
        resp: LLMResponse = complete(prompt, system=system, temperature=0.7)
        if not resp.text:
            raise DraftV2Error("LLM returned empty response")
        data = _safe_json(resp.text)
        # Reject partial objects: every expected key should be present.
        missing = [k for k in _DRAFT_JSON_KEYS if k not in data]
        if missing:
            raise DraftV2Error(f"Missing keys in LLM output: {missing}")
        draft = _hydrate_draft(item, score, data, day_plan, image_path=image_path)
        return draft
    except (json.JSONDecodeError, DraftV2Error, ValidationError, TypeError, ValueError) as e:
        logger.warning("LLM draft failed for %s: %s; falling back to rule-based", item.id, e)
        draft = draft_item(item, score)
        draft.image_path = image_path
        return draft


def draft_for_day(
    item: Item,
    score: ScoreResult,
    for_date: datetime | None = None,
    with_image: bool = False,
) -> Draft:
    """Convenience wrapper that resolves a calendar day and drafts for it."""
    target = for_date.date() if for_date else datetime.now(timezone.utc).date()
    day_plan = post_type_for_date(target)
    return draft_item_v2(item, score, day_plan=day_plan, with_image=with_image)
