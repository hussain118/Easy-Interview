"""Centralized OpenAI access.

All GPT calls in this project (JD parsing, resume parsing, GitHub analysis,
gap analysis, question planning, and — in later phases — answer evaluation
and scoring) go through this module. Nothing else should import `openai`
directly. This keeps prompts/model/params consistent and makes call-count
auditing possible in one place.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openai import OpenAI

from src.config import get_optional_key, require_key

_client: OpenAI | None = None

# The provided OPENAI_API_KEY is an OpenRouter key (sk-or-v1-...), not an
# official OpenAI key, so we route through OpenRouter's OpenAI-compatible
# endpoint. Model names must therefore be OpenRouter-style
# ("openai/gpt-4o-mini"), not bare OpenAI model names.
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-4o-mini"

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


def get_client() -> OpenAI:
    global _client
    if _client is None:
        base_url = get_optional_key("OPENAI_BASE_URL") or DEFAULT_BASE_URL
        _client = OpenAI(api_key=require_key("OPENAI_API_KEY"), base_url=base_url)
    return _client


def load_prompt(filename: str) -> str:
    """Read a system prompt from prompts/<filename>. Prompts live as files,
    never inline strings, so they can be versioned and diffed (see
    prompts/ITERATION_NOTES.md).
    """
    path = PROMPTS_DIR / filename
    return path.read_text(encoding="utf-8")


def structured_completion(
    *,
    system_prompt: str,
    user_content: str,
    json_schema: dict[str, Any],
    schema_name: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2,
) -> dict[str, Any]:
    """Call GPT with a strict JSON schema response format and return parsed JSON.

    Uses OpenAI structured outputs so we never depend on parsing free-form
    prose out of the model's reply. Thin wrapper over
    structured_completion_with_usage() for callers that don't need usage
    metrics (kept so existing agents don't need to change).
    """
    parsed, _usage = structured_completion_with_usage(
        system_prompt=system_prompt,
        user_content=user_content,
        json_schema=json_schema,
        schema_name=schema_name,
        model=model,
        temperature=temperature,
    )
    return parsed


def structured_completion_with_usage(
    *,
    system_prompt: str,
    user_content: str,
    json_schema: dict[str, Any],
    schema_name: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2,
    prompt_cache_key: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Same as structured_completion(), but also returns a usage dict:
    {"input_tokens", "cached_tokens", "output_tokens"} — for prompt-caching
    observability (see src/agents/cache_metrics.py). `system_prompt` should
    be the STABLE part of the request (put it first, keep it byte-identical
    across calls) for it to actually be eligible for prompt caching;
    `user_content` is the dynamic per-call suffix.

    `prompt_cache_key` groups requests for cache routing purposes (OpenAI
    Chat Completions param). It must never contain candidate-specific
    content (e.g. the answer text) — pass something like
    "interview-evaluator-v1" or "interview-evaluator-v1:{role_hash}".
    """
    client = get_client()
    kwargs: dict[str, Any] = dict(
        model=model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "schema": json_schema,
                "strict": True,
            },
        },
    )
    if prompt_cache_key:
        kwargs["prompt_cache_key"] = prompt_cache_key

    response = client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content
    parsed = json.loads(content)

    usage = response.usage
    cached_tokens = 0
    input_tokens = 0
    output_tokens = 0
    if usage is not None:
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        details = getattr(usage, "prompt_tokens_details", None)
        if details is not None:
            cached_tokens = getattr(details, "cached_tokens", 0) or 0

    return parsed, {
        "input_tokens": input_tokens,
        "cached_tokens": cached_tokens,
        "output_tokens": output_tokens,
    }
