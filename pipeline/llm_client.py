"""Provider-agnostic LLM client.

Defaults to a local Ollama endpoint (OpenAI-compatible server at
http://127.0.0.1:11434/v1). Optionally uses OpenAI or Anthropic when
configured via environment variables.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)
from dataclasses import dataclass

import requests


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


LLM_PROVIDER = _env("LLM_PROVIDER", "ollama").lower()
LLM_API_KEY = _env("LLM_API_KEY", "")
LLM_BASE_URL = _env("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
# Default to a small, widely available Ollama model. Override via LLM_MODEL env var.
LLM_MODEL = _env("LLM_MODEL", "llama3.2")
LLM_TIMEOUT = int(_env("LLM_TIMEOUT", "120"))


@dataclass
class LLMResponse:
    text: str
    model: str = ""
    finish_reason: str = ""


def _ollama_complete(prompt: str, system: str = "", temperature: float = 0.7) -> LLMResponse:
    """Call an OpenAI-compatible endpoint served by Ollama or similar."""
    url = LLM_BASE_URL.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=LLM_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    choice = data.get("choices", [{}])[0]
    message = choice.get("message", {})
    return LLMResponse(
        text=message.get("content", ""),
        model=data.get("model", LLM_MODEL),
        finish_reason=choice.get("finish_reason", ""),
    )


def _openai_complete(prompt: str, system: str = "", temperature: float = 0.7) -> LLMResponse:
    from openai import OpenAI

    client = OpenAI(api_key=LLM_API_KEY, base_url=None)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    resp = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        temperature=temperature,
        timeout=LLM_TIMEOUT,
    )
    return LLMResponse(
        text=resp.choices[0].message.content or "",
        model=resp.model,
        finish_reason=resp.choices[0].finish_reason or "",
    )


def _anthropic_complete(prompt: str, system: str = "", temperature: float = 0.7) -> LLMResponse:
    import anthropic

    client = anthropic.Anthropic(api_key=LLM_API_KEY)
    resp = client.messages.create(
        model=LLM_MODEL,
        max_tokens=4096,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        timeout=LLM_TIMEOUT,
    )
    content_blocks = resp.content or []
    text = "\n".join(block.text for block in content_blocks if getattr(block, "type", None) == "text")
    return LLMResponse(
        text=text,
        model=resp.model,
        finish_reason=resp.stop_reason or "",
    )


def complete(prompt: str, system: str = "", temperature: float = 0.7) -> LLMResponse:
    """Complete a prompt using the configured provider."""
    if LLM_PROVIDER == "ollama":
        return _ollama_complete(prompt, system, temperature)
    if LLM_PROVIDER == "openai":
        return _openai_complete(prompt, system, temperature)
    if LLM_PROVIDER == "anthropic":
        return _anthropic_complete(prompt, system, temperature)
    raise RuntimeError(f"Unsupported LLM_PROVIDER: {LLM_PROVIDER}")


def is_available() -> bool:
    """Return True if the configured provider appears reachable."""
    if LLM_PROVIDER in {"openai", "anthropic"}:
        return bool(LLM_API_KEY)
    if LLM_PROVIDER == "ollama":
        try:
            resp = requests.get(LLM_BASE_URL.rstrip("/") + "/models", timeout=5)
            return resp.status_code == 200
        except requests.exceptions.RequestException:
            logger.debug("Ollama availability check failed", exc_info=True)
            return False
    return False


def summarize_text(text: str, max_words: int = 120) -> str:
    """Ask the LLM to summarize arbitrary text into a short paragraph."""
    system = "You summarize content for AI-builder professionals. Be concise, factual, and technical."
    prompt = (
        f"Summarize the following content in no more than {max_words} words, "
        "highlighting what changed and why builders should care:\n\n"
        f"{text[:4000]}"
    )
    return complete(prompt, system=system, temperature=0.4).text.strip()


def draft_from_summary(title: str, summary: str, source_url: str) -> dict:
    """Generate a LinkedIn-style draft from a content summary."""
    system = (
        "You draft LinkedIn posts for AI builders. Output only JSON with keys: "
        "linkedin_post, newsletter_section, short_pill, forward_pill, narrative_pill, hashtags. "
        "Keep linkedin_post under 250 words, human and direct, no buzzwords."
    )
    prompt = (
        f"Title: {title}\n\n"
        f"Source: {source_url}\n\n"
        f"Summary:\n{summary}\n\n"
        "Draft a LinkedIn post and derivative snippets. Return valid JSON only."
    )
    raw = complete(prompt, system=system, temperature=0.7).text.strip()
    # Strip markdown code fences if the model wrapped JSON in them.
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
        raw = raw.removesuffix("```")
        raw = raw.strip()
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError, TypeError):
        logger.warning("Failed to parse LLM JSON draft; returning raw text fallback", exc_info=True)
        return {
            "linkedin_post": raw,
            "newsletter_section": "",
            "short_pill": "",
            "forward_pill": "",
            "narrative_pill": "",
            "hashtags": [],
        }
