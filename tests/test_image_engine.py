"""Tests for pipeline.image_engine."""

import pytest

from pipeline.image_engine import (
    FAL_KEY,
    _clean_for_prompt,
    _extract_pexels_query,
    available_providers,
    image_for_post,
    prompt_for_post,
)


def test_clean_for_prompt_strips_urls_and_tags():
    raw = "Check this out! https://example.com #AI #BuilderTools"
    assert "https://" not in _clean_for_prompt(raw)
    assert "#" not in _clean_for_prompt(raw)


def test_prompt_for_post_has_no_text_request():
    p = prompt_for_post("Monday", "tool_drop", "New AI tool drops", "We got a tool.", "#AI")
    assert "no text" in p.lower() or "free of text" in p.lower()
    assert "1.91:1" in p or "landscape" in p.lower()


def test_prompt_for_post_matches_day_style():
    viral = prompt_for_post("Tuesday", "viral_explained", "Gemini 3.7", "post", "#AI")
    assert "bold" in viral.lower() or "news-style" in viral.lower()

    security = prompt_for_post("Friday", "security_signal", "Red team", "post", "#AI")
    assert "cybersecurity" in security.lower() or "red-team" in security.lower()


def test_extract_pexels_query_matches_pillar():
    assert "cybersecurity" in _extract_pexels_query("Friday", "security_signal", "x")
    assert "business" in _extract_pexels_query("Saturday", "founder_signal", "x")


def test_available_providers_defaults():
    providers = available_providers()
    assert "pollinations" in providers
    # fal appears only if FAL_KEY is set in env
    if FAL_KEY:
        assert "fal" in providers


@pytest.mark.skip(reason="network call")
def test_image_for_post_network_pollinations():
    _p, src = image_for_post(
        item_url="https://example.com/no-og-image-here",
        title="AI security visual",
        day="Friday",
        pillar="security_signal",
        linkedin_post="Security signal.",
        hashtags="#AISecurity",
        skip_og=True,
        provider="pollinations",
    )
    assert src in {"pollinations", ""}


@pytest.mark.skipif(not FAL_KEY, reason="FAL_KEY not configured")
@pytest.mark.skip(reason="network call")
def test_image_for_post_network_fal():
    _p, src = image_for_post(
        item_url="https://example.com/no-og-image-here",
        title="AI security visual",
        day="Friday",
        pillar="security_signal",
        linkedin_post="Security signal.",
        hashtags="#AISecurity",
        skip_og=True,
        provider="fal",
    )
    assert src == "fal"
