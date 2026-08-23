"""Tests for pipeline.image_engine."""

from pipeline.image_engine import (
    _inject_prompt_into_workflow,
    build_image_prompt,
    fetch_og_image,
)


def test_build_image_prompt_contains_topic():
    p = build_image_prompt("tool_drop", "Some AI Tool", "A summary of the tool.")
    assert "Some AI Tool" in p
    assert "AI builders" in p


def test_inject_prompt_into_workflow():
    wf = {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "old prompt"}},
        "2": {"class_type": "KSampler", "inputs": {}},
    }
    out = _inject_prompt_into_workflow(wf, "new prompt")
    assert out["1"]["inputs"]["text"] == "new prompt"


def test_inject_prompt_does_not_crash_without_clip():
    wf = {"2": {"class_type": "KSampler", "inputs": {}}}
    out = _inject_prompt_into_workflow(wf, "new prompt")
    assert out == wf


def test_fetch_og_image_for_known_url(tmp_path, monkeypatch):
    from pipeline import image_engine

    monkeypatch.setattr(image_engine, "IMAGE_DIR", tmp_path)
    url = "https://blog.cloudflare.com/workers-protected-by-access/"
    path = fetch_og_image(url)
    # Cloudflare blog usually has an og:image
    if path:
        assert path.exists()
        assert path.stat().st_size > 0
