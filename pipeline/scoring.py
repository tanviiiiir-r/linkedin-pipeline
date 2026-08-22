"""Score collected items against content pillars and signals."""
import re
from typing import Optional

from pydantic import BaseModel

from config.settings import CLAIM_KEYWORDS, PILLARS
from pipeline.storage import Item


class ScoreResult(BaseModel):
    pillar: Optional[str] = None
    pillar_confidence: int = 0  # 0-100
    signal_strength: int = 0  # 0-100
    reason: str = ""


def score_item(item: Item) -> ScoreResult:
    """Rule-based scoring. LLM-based refinement can be added later by Hermes."""
    text = " ".join([item.item_title, item.summary, *item.key_claims, item.raw_content]).lower()
    if not text.strip():
        return ScoreResult(reason="no content to score")

    pillar, confidence = _best_pillar(text)
    signal = _signal_strength(item, text)
    return ScoreResult(
        pillar=pillar,
        pillar_confidence=confidence,
        signal_strength=signal,
        reason=f"matched pillar '{pillar}' at {confidence}%, signal {signal}%",
    )


def _best_pillar(text: str) -> tuple[Optional[str], int]:
    scores: dict[str, int] = {}

    # Tool Drop: mentions specific tools/APIs/frameworks
    tool_signals = ["tool", "api", "framework", "library", "sdk", "plugin", "launch", "released"]
    scores["tool_drop"] = sum(15 for s in tool_signals if s in text)

    # Viral Explained: trending, launch, demo, explainer
    viral_signals = ["viral", "trending", "demo", "launch", "explained", "why", "how", "watch"]
    scores["viral_explained"] = sum(15 for s in viral_signals if s in text)

    # Pattern Spotting: connects signals, workflow, pattern
    pattern_signals = ["pattern", "workflow", "emerging", "shift", "trend", "connect", "combine"]
    scores["pattern_spotting"] = sum(15 for s in pattern_signals if s in text)

    # Builder Memo: practical, tutorial, cost, performance, prompt
    builder_signals = ["how to", "tutorial", "workflow", "prompt", "cost", "perf", "trick", "build"]
    scores["builder_memo"] = sum(15 for s in builder_signals if s in text)

    # Tomorrow in AI: prediction, future, question, will, next
    future_signals = ["prediction", "future", "next", "will", "question", "what if", "could"]
    scores["tomorrow_in_ai"] = sum(15 for s in future_signals if s in text)

    best = max(scores, key=scores.get)
    return (best, min(scores[best], 100)) if scores[best] > 0 else (None, 0)


def _signal_strength(item: Item, text: str) -> int:
    score = 0
    if "hacker news" in item.source_name.lower() or "hn" in item.source_name.lower():
        score += 30
    if "github" in item.source_name.lower():
        score += 25
    if any(k in text for k in CLAIM_KEYWORDS):
        score += 20
    if item.key_claims:
        score += min(len(item.key_claims) * 5, 25)
    return min(score, 100)


def is_worthy(item: Item, min_confidence: int = 50, min_signal: int = 40) -> bool:
    result = score_item(item)
    return bool(result.pillar and result.pillar_confidence >= min_confidence and result.signal_strength >= min_signal)
