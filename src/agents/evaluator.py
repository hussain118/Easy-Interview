"""GPT-based candidate answer evaluator + deterministic normalization.

Only relevant context is sent to GPT (the specific question + a couple of
prior turns + the evidence the question was grounded in) — never the full
resume/JD/GitHub JSON blobs.

Prompt-caching structure: the system prompt (prompts/answer_evaluator.md)
is the STABLE PREFIX — long, detailed, and byte-identical across every
call (rubric, quality definitions, guardrail/fairness/evidence rules,
output schema). Everything that varies per turn (question, answer,
competency, evidence reference, prior turns) goes in the user message,
which is sent AFTER the stable prefix — this is what makes the request
prefix-cacheable rather than one giant re-assembled blob. See
prompts/ITERATION_NOTES.md for the v1->v2 rationale and
src/agents/cache_metrics.py for how cache effectiveness is measured.
"""
from __future__ import annotations

import json
from typing import Any

from src.agents import cache_metrics
from src.providers.openai_client import (
    DEFAULT_MODEL,
    load_prompt,
    structured_completion_with_usage,
)

VALID_QUALITIES = {"strong", "good", "shallow", "bluff", "off_topic", "unclear"}
VALID_ACTIONS = {"next_question", "follow_up", "increase_difficulty", "verify", "recovery"}

# Deterministic, non-PII cache key: groups all evaluator calls for cache
# routing without ever including candidate-specific content (the answer
# text stays in the dynamic user message, never in this key).
EVALUATOR_CACHE_KEY = "interview-evaluator-v1"

EVALUATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "quality": {"type": "string", "enum": sorted(VALID_QUALITIES)},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
        "recommended_action": {"type": "string", "enum": sorted(VALID_ACTIONS)},
    },
    "required": ["quality", "confidence", "reason", "recommended_action"],
    "additionalProperties": False,
}


def evaluate_answer(
    *,
    question_text: str,
    competency: str,
    difficulty: str,
    source_reference: str,
    candidate_answer: str,
    prior_turns: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    system_prompt = load_prompt("answer_evaluator.md")  # stable prefix — see module docstring
    payload = {
        "question": question_text,
        "competency": competency,
        "difficulty": difficulty,
        "evidence_grounding": source_reference,
        "candidate_answer": candidate_answer,
        "recent_prior_turns_on_this_topic": prior_turns or [],
    }
    raw, usage = structured_completion_with_usage(
        system_prompt=system_prompt,
        user_content=json.dumps(payload, indent=2),
        json_schema=EVALUATION_SCHEMA,
        schema_name="evaluation_schema",
        temperature=0.0,
        prompt_cache_key=EVALUATOR_CACHE_KEY,
    )
    cache_metrics.record(
        model=DEFAULT_MODEL,
        purpose="answer_evaluation",
        input_tokens=usage["input_tokens"],
        cached_tokens=usage["cached_tokens"],
        output_tokens=usage["output_tokens"],
    )
    return normalize_evaluation(raw)


def normalize_evaluation(raw: dict[str, Any]) -> dict[str, Any]:
    """Deterministic validation of the GPT evaluator output. Never lets
    unvalidated LLM text flow into graph routing.
    """
    quality = raw.get("quality")
    if quality not in VALID_QUALITIES:
        quality = "unclear"

    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    action = raw.get("recommended_action")
    if action not in VALID_ACTIONS:
        action = "next_question"

    reason = str(raw.get("reason") or "").strip()[:500]

    return {
        "quality": quality,
        "confidence": confidence,
        "reason": reason,
        "recommended_action": action,
    }


SILENCE_EVALUATION = {
    "quality": "unclear",
    "confidence": 1.0,
    "reason": "No answer given (silence/empty response).",
    "recommended_action": "recovery",
}
