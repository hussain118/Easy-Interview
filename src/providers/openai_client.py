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
    prose out of the model's reply.
    """
    client = get_client()
    response = client.chat.completions.create(
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
    content = response.choices[0].message.content
    return json.loads(content)
