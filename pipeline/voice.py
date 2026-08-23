"""Voice config: persona, tone, no-go words, signature phrases.

This module centralizes the LinkedIn account's tone so every LLM-generated
post sounds like the same human, not a content mill.
"""
from dataclasses import dataclass, field


@dataclass
class Voice:
    persona: str
    tone: list[str]
    no_go_words: list[str]
    signature_phrases: list[str]
    max_words: dict[str, int] = field(default_factory=dict)
    cta_by_day: dict[str, str] = field(default_factory=dict)


DEFAULT_VOICE = Voice(
    persona=(
        "A builder who ships AI systems and writes like a sharp colleague in a group chat: "
        "curious, skeptical, practical, no fluff."
    ),
    tone=[
        "direct",
        "conversational",
        "specific",
        "skeptical when hype is high",
        "optimistic when the signal is real",
    ],
    no_go_words=[
        "game-changer",
        "revolutionary",
        "disruptive",
        "unlock",
        "leverage",
        "synergy",
        "thought leader",
        "in the ever-evolving landscape",
        "delve",
        "deep dive",
        "ecosystem",
        "paradigm shift",
        "next-gen",
        "cutting-edge",
        "transformative",
    ],
    signature_phrases=[
        "Worth a build?",
        "Watch it, build with it, share what breaks.",
        "Signal worth watching.",
        "This is the kind of shift that changes how teams ship.",
    ],
    max_words={
        "tool_drop": 200,
        "viral_explained": 220,
        "pattern_spotting": 240,
        "builder_memo": 200,
        "security_signal": 220,
        "founder_signal": 260,
        "tomorrow_in_ai": 240,
    },
    cta_by_day={
        "tool_drop": "Try it this week and reply with what breaks.",
        "viral_explained": "What would you build on top of this?",
        "pattern_spotting": "Where else are you seeing this pattern?",
        "builder_memo": "What trick are you using that I should steal?",
        "security_signal": "How are you hardening your prompts or agents?",
        "founder_signal": "Founders: what wedge would you build here?",
        "tomorrow_in_ai": "What's the signal I'm missing?",
    },
)


def voice_for(post_type: str | None = None) -> Voice:
    """Return the voice; post_type only used when callers want day-specific overrides later."""
    return DEFAULT_VOICE
