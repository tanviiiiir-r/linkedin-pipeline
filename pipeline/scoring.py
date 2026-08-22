"""Score collected items against content pillars and signals.

V2: tighter scoring that filters low-signal content (e.g. Reddit rants) and
boosts high-signal sources. Uses topic taxonomy for relevance.
"""
import re
from typing import Optional

from pydantic import BaseModel

from config.settings import CLAIM_KEYWORDS, PILLARS
from pipeline.storage import Item
from pipeline.topics import extract_topics, primary_topic


class ScoreResult(BaseModel):
    pillar: Optional[str] = None
    pillar_confidence: int = 0  # 0-100
    signal_strength: int = 0  # 0-100
    reason: str = ""
    topics: list[str] = []
    primary_topic: Optional[str] = None


# Sources we trust to produce high-signal content
_HIGH_SIGNAL_SOURCES = {
    "portswigger", "the hacker news", "bleepingcomputer", "dark reading",
    "cloudflare", "github security", "aws security", "sans", "arXiv",
    "nvidia", "google cloud", "deepmind", "latent space", "langchain",
    "interconnects", "hacker news",
}

_LOW_SIGNAL_SOURCES = {
    "reddit", "product hunt", "instagram",
}

_EVIDENCE_WORDS = {
    "paper", "research", "study", "benchmark", "experiment", "dataset",
    "github.com", "repo", "release", "launch", "report", "advisory",
    "cve", "vulnerability", "exploit", "attack", "rce", "xss", "injection",
    "disclosed", "patch", "mitigation",
}

_TECHNICAL_DEPTH_WORDS = {
    "architecture", "implementation", "evaluation", "methodology",
    "ablation", "latency", "throughput", "cost", "deployment", "infrastructure",
    "quantization", "distillation", "fine-tune", "post-training", "rlhf",
}


def score_item(item: Item) -> ScoreResult:
    """Rule-based scoring with source quality and evidence checks."""
    text = " ".join([item.item_title, item.summary, *item.key_claims, item.raw_content]).lower()
    if not text.strip():
        return ScoreResult(reason="no content to score")

    topics = extract_topics(text, top_n=5)

    # Filter noise: very short content without evidence words
    if _is_noise(item, text):
        return ScoreResult(
            pillar=None,
            pillar_confidence=0,
            signal_strength=0,
            reason="low-signal content (too short / no evidence)",
            topics=topics,
            primary_topic=primary_topic(topics),
        )

    pillar, confidence = _best_pillar(text, topics)
    signal = _signal_strength(item, text, topics)
    return ScoreResult(
        pillar=pillar,
        pillar_confidence=confidence,
        signal_strength=signal,
        reason=f"matched pillar '{pillar}' at {confidence}%, signal {signal}%",
        topics=topics,
        primary_topic=primary_topic(topics),
    )


def _is_noise(item: Item, text: str) -> bool:
    """Detect low-signal content like rants, memes, and unsupported claims."""
    source_lower = item.source_name.lower()

    # Product Hunt without technical substance is low-signal for our audience
    if "product hunt" in source_lower:
        has_tech = any(w in text for w in _TECHNICAL_DEPTH_WORDS) or any(w in text for w in _EVIDENCE_WORDS)
        # But if it explicitly mentions API/framework/release, keep it
        has_tool_signals = any(s in text for s in ["api", "framework", "sdk", "tool", "launch", "release"])
        if not has_tech and not has_tool_signals:
            return True

    # Reddit/short-form noise: very short selftext and no evidence
    if any(s in source_lower for s in _LOW_SIGNAL_SOURCES):
        word_count = len(text.split())
        has_evidence = any(w in text for w in _EVIDENCE_WORDS)
        has_technical = any(w in text for w in _TECHNICAL_DEPTH_WORDS)
        if word_count < 80 and not (has_evidence or has_technical):
            return True
        # Discussion-only titles (rant markers)
        rant_markers = ["i ", "my ", "rant", "interview", "career", "job", "fired", "laid off", "fuck"]
        if any(item.item_title.lower().startswith(m) for m in rant_markers):
            return True
        if any(m in item.item_title.lower() for m in rant_markers[3:]):
            return True

    return False


def _best_pillar(text: str, topics: list[str]) -> tuple[Optional[str], int]:
    scores: dict[str, int] = {}
    text_lower = text.lower()

    # Tool Drop: specific tools/APIs/frameworks/releases
    tool_signals = ["tool", "api", "framework", "library", "sdk", "plugin", "release", "launched", "open source"]
    scores["tool_drop"] = sum(15 for s in tool_signals if s in text_lower)
    if any(t in {"ai-devtools", "mcp", "coding-agents"} for t in topics):
        scores["tool_drop"] += 25

    # Viral Explained: trending launch/demo/explainer
    viral_signals = ["demo", "explained", "new model", "released", "announced", "watch"]
    scores["viral_explained"] = sum(15 for s in viral_signals if s in text_lower)
    if "new-model" in topics or "multimodal" in topics:
        scores["viral_explained"] += 25

    # Pattern Spotting: connects signals/workflow/shift
    pattern_signals = ["pattern", "workflow", "shift", "trend", "move toward", "convergence"]
    scores["pattern_spotting"] = sum(15 for s in pattern_signals if s in text_lower)
    if any(t in {"agent-orchestration", "llmops", "mlops"} for t in topics):
        scores["pattern_spotting"] += 25

    # Builder Memo: practical, tutorial, cost, performance, build/deploy
    builder_signals = ["how to", "tutorial", "build", "deploy", "cost", "performance", "latency", "optimize"]
    scores["builder_memo"] = sum(15 for s in builder_signals if s in text_lower)
    if any(t in {"ai-systems", "ai-efficiency", "deployment", "inference"} for t in topics):
        scores["builder_memo"] += 25

    # Tomorrow in AI: prediction, future, question
    future_signals = ["prediction", "future", "next", "what if", "could", "will change"]
    scores["tomorrow_in_ai"] = sum(15 for s in future_signals if s in text_lower)

    # Security override: if strong security topics, boost pattern_spotting or builder_memo
    security_topics = {
        "agent-security", "prompt-injection", "model-security", "ai-red-teaming",
        "tool-security", "sandboxing", "data-exfiltration", "supply-chain-security",
    }
    if any(t in security_topics for t in topics):
        scores["builder_memo"] = max(scores.get("builder_memo", 0), 60)

    best = max(scores, key=scores.get)
    return (best, min(scores[best], 100)) if scores[best] >= 30 else (None, 0)


def _signal_strength(item: Item, text: str, topics: list[str]) -> int:
    score = 0
    source_lower = item.source_name.lower()

    # Source quality boost
    if any(s in source_lower for s in _HIGH_SIGNAL_SOURCES):
        score += 35
    elif any(s in source_lower for s in _LOW_SIGNAL_SOURCES):
        score -= 20

    # Evidence / technical depth
    evidence_hits = sum(1 for w in _EVIDENCE_WORDS if w in text)
    technical_hits = sum(1 for w in _TECHNICAL_DEPTH_WORDS if w in text)
    score += min(evidence_hits * 8, 30)
    score += min(technical_hits * 6, 25)

    # Topic relevance
    if topics:
        score += min(len(topics) * 5, 20)

    # Generic evidence fallback: title mentions tool/api/framework/release
    if any(w in item.item_title.lower() for w in ["api", "framework", "sdk", "tool", "release", "launched"]):
        score += 20

    # Reddit-specific: boost high engagement with evidence
    if item.reddit_score and item.reddit_score > 100 and evidence_hits >= 2:
        score += 15

    return max(0, min(score, 100))


def is_worthy(item: Item, min_confidence: int = 50, min_signal: int = 40) -> bool:
    result = score_item(item)
    return bool(
        result.pillar
        and result.pillar_confidence >= min_confidence
        and result.signal_strength >= min_signal
        and not _is_noise(item, " ".join([item.item_title, item.summary, *item.key_claims, item.raw_content]).lower())
    )


if __name__ == "__main__":
    from pipeline.storage import Item
    test = Item(
        source_name="PortSwigger",
        source_url="https://portswigger.net",
        item_url="https://example.com",
        item_title="LLM agent tool injection leads to RCE in customer SaaS",
        summary="Researchers demonstrate indirect prompt injection via tool use.",
        source_type="rss",
        content_type="article",
        key_claims=["RCE achieved via tool injection", "affects 3 major platforms"],
        raw_content="paper benchmark evaluation methodology",
    )
    r = score_item(test)
    print(r)
