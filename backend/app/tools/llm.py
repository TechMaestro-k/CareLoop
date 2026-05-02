"""Groq LLM wrapper for both reasoning (Llama 3.3 70B) and NLU (Llama 3.1 8B Instant).

The wrapper exposes two entrypoints:
  - chat_json(prompt_key, **vars)  — returns parsed JSON dict
  - chat_text(prompt_key, **vars)  — returns plain text

On 429 rate-limit errors, both automatically retry once using the fast
llama-3.1-8b-instant fallback model so conversations stay live even when
the daily token quota on the large model is exhausted.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from groq import Groq

from app.config import settings
from app.prompts.registry import get_prompt, render

log = logging.getLogger(__name__)

_FALLBACK_MODEL = "llama-3.1-8b-instant"

_client: Groq | None = None


def _client_singleton() -> Groq | None:
    global _client
    if _client is not None:
        return _client
    if not settings.groq_api_key:
        log.warning("GROQ_API_KEY not set — LLM calls will return empty {}.")
        return None
    _client = Groq(api_key=settings.groq_api_key)
    return _client


def _is_rate_limit_error(exc: Exception) -> bool:
    """Detect Groq 429 rate-limit errors."""
    msg = str(exc).lower()
    return "429" in msg or "rate_limit" in msg or "rate limit" in msg


def _call_groq_json(client: Groq, model: str, temperature: float, messages: list, max_tokens: int = 2048) -> dict:
    """Single Groq JSON call. Raises on any error."""
    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        response_format={"type": "json_object"},
        messages=messages,
        max_tokens=max_tokens,
    )
    content = resp.choices[0].message.content or "{}"
    return json.loads(content)


def _call_groq_text(client: Groq, model: str, temperature: float, messages: list, max_tokens: int = 1024) -> str:
    """Single Groq text call. Raises on any error."""
    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        messages=messages,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""


def chat_json(prompt_key: str, **vars: Any) -> dict[str, Any]:
    """Call Groq with the named prompt; return parsed JSON dict.

    On 429 rate-limit, retries once with the fast fallback model.
    On any other failure, returns {} so callers can degrade gracefully.
    """
    client = _client_singleton()
    if client is None:
        return {}

    try:
        prompt = get_prompt(prompt_key)
    except Exception as e:
        log.error("Prompt %s not found: %s", prompt_key, e)
        return {}

    model = prompt.get("model") or settings.groq_model_reasoning
    temperature = prompt.get("temperature", 0.2)
    system = prompt.get("system", "").strip()
    user = render(prompt.get("user", "").strip(), **vars)

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})

    try:
        return _call_groq_json(client, model, temperature, messages)
    except json.JSONDecodeError as e:
        log.error("LLM returned invalid JSON for %s: %s", prompt_key, e)
        return {}
    except Exception as e:
        if _is_rate_limit_error(e) and model != _FALLBACK_MODEL:
            log.warning(
                "Rate limit on %s for prompt %s — retrying with %s",
                model, prompt_key, _FALLBACK_MODEL,
            )
            try:
                return _call_groq_json(client, _FALLBACK_MODEL, temperature, messages)
            except json.JSONDecodeError as e2:
                log.error("Fallback LLM returned invalid JSON for %s: %s", prompt_key, e2)
                return {}
            except Exception as e2:
                log.error("Fallback LLM call also failed for %s: %s", prompt_key, e2)
                return {}
        log.error("LLM call failed for %s: %s", prompt_key, e)
        return {}


def chat_text(prompt_key: str, **vars: Any) -> str:
    """Same as chat_json but returns plain text (no response_format constraint).

    On 429 rate-limit, retries once with the fast fallback model.
    """
    client = _client_singleton()
    if client is None:
        return ""
    try:
        prompt = get_prompt(prompt_key)
    except Exception as e:
        log.error("Prompt %s not found: %s", prompt_key, e)
        return ""
    model = prompt.get("model") or settings.groq_model_reasoning
    temperature = prompt.get("temperature", 0.4)
    system = prompt.get("system", "").strip()
    user = render(prompt.get("user", "").strip(), **vars)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    try:
        return _call_groq_text(client, model, temperature, messages)
    except Exception as e:
        if _is_rate_limit_error(e) and model != _FALLBACK_MODEL:
            log.warning(
                "Rate limit on %s for prompt %s — retrying with %s",
                model, prompt_key, _FALLBACK_MODEL,
            )
            try:
                return _call_groq_text(client, _FALLBACK_MODEL, temperature, messages)
            except Exception as e2:
                log.error("Fallback LLM text call also failed for %s: %s", prompt_key, e2)
                return ""
        log.error("LLM text call failed: %s", e)
        return ""
