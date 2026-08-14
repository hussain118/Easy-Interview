"""GPT-based candidate answer evaluator + deterministic normalization.

Only relevant context is sent to GPT (the specific question + a couple of
prior turns + the evidence the question was grounded in) — never the full
resume/JD/GitHub JSON blobs.
"""
from __future__ import annotations

import json
from typing import Any

from src.providers.openai_client import load_prompt, structured_completion

VALID_QUALITIES = {"strong", "good", "shallow", "bluff", "off_topic", "unclear"}
VALID_ACTIONS = {"next_question", "follow_up", "increase_difficulty", "verify", "recovery"}

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
    system_prompt = load_prompt("evaluator_v1.md")
    payload = {
        "question": question_text,
        "competency": competency,
        "difficulty": difficulty,
        "evidence_grounding": source_reference,
        "candidate_answer": candidate_answer,
        "recent_prior_turns_on_this_topic": prior_turns or [],
    }
    raw = structured_completion(
        system_prompt=system_prompt,
        user_content=json.dumps(payload, indent=2),
        json_schema=EVALUATION_SCHEMA,
        schema_name="evaluation_schema",
        temperature=0.0,
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
