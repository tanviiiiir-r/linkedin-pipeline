"""Tests for pipeline.image_engine."""
from pathlib import Path

import pytest

from pipeline.image_engine import _clean_for_prompt, image_for_post, prompt_for_post


def test_clean_for_prompt_strips_urls_and_tags():
    raw = "Check this out! https://example.com #AI #BuilderTools"
    assert "https://" not in _clean_for_prompt(raw)
    assert "#" not in _clean_for_prompt(raw)


def test_prompt_for_post_has_no_text_request():
    p = prompt_for_post("Monday", "tool_drop", "New AI tool drops", "We got a tool.", "#AI")
    assert "No text" in p or "free of text" in p.lower()
    assert "1.91:1" in p or "landscape" in p.lower()


def test_prompt_for_post_matches_day_style():
    viral = prompt_for_post("Tuesday", "viral_explained", "Gemini 3.7", "post", "#AI")
    assert "bold" in viral.lower() or "news-style" in viral.lower()

    security = prompt_for_post("Friday", "security_signal", "Red team", "post", "#AI")
    assert "cybersecurity" in security.lower() or "red-team" in security.lower()


@pytest.mark.skip(reason="network call")
def test_image_for_post_network():
    p = image_for_post(
        item_url="https://example.com/no-og-image-here",
        title="AI security visual",
        day="Friday",
        pillar="security_signal",
        linkedin_post="Security signal.",
        hashtags="#AISecurity",
        skip_og=True,
    )
    assert p is None or isinstance(p, Path)
