"""GPT-based final scorer -> output/scorecard.json (exact PDF §6 schema).

Prompt structure (cache-friendly, per spec):
  STABLE PREFIX     prompts/final_scorer.md — byte-identical every call
  STATIC CONTEXT     role, competency list, compact resume claims,
                      compact GitHub evidence (never the raw repo)
  DYNAMIC SUFFIX      transcript + per-answer evaluations, transcript LAST

candidate_name/role/interview_date/duration_seconds and
github_grounded_questions_asked are filled deterministically from known
values, never left to the LLM to state or count.

Cross-candidate isolation: nothing here is cached beyond the STABLE
PREFIX (rubric/schema/instructions). prompt_cache_key is fixed
("first-round-final-scorer-v1") and contains no candidate data; the
candidate-specific transcript/resume/GitHub content is sent fresh in the
dynamic suffix on every call and is never written to any shared/global
cache — only OpenAI's own request-level prompt caching (keyed off the
byte-identical stable prefix) applies, which by construction cannot leak
one candidate's dynamic content into another candidate's request.
"""
from __future__ import annotations

import json
from typing import Any

from src.agents import cache_metrics
from src.guardrails.evidence_check import validate_scorecard_evidence
from src.providers.openai_client import (
    DEFAULT_MODEL,
    load_prompt,
    structured_completion_with_usage,
)

FINAL_SCORER_CACHE_KEY = "first-round-final-scorer-v1"

_GPT_SCORECARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "competencies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "score": {"type": "integer"},
                    "confidence": {"type": "number"},
                    "evidence_quote": {"type": "string"},
                    "reasoning": {"type": "string"},
                },
                "required": ["name", "score", "confidence", "evidence_quote", "reasoning"],
                "additionalProperties": False,
            },
        },
        "overall_score": {"type": "number"},
        "recommendation": {"type": "string", "enum": ["hire", "no_hire", "borderline"]},
        "recommendation_reasoning": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "concerns": {"type": "array", "items": {"type": "string"}},
        "guardrail_flags": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "competencies", "overall_score", "recommendation", "recommendation_reasoning",
        "strengths", "concerns", "guardrail_flags",
    ],
    "additionalProperties": False,
}


def _compact_resume_claims(resume: dict[str, Any]) -> list[str]:
    return (resume or {}).get("claims", [])[:15]


def _compact_github_evidence(github: dict[str, Any]) -> dict[str, Any]:
    """Never the raw repository — just the already-condensed analysis and
    repo names, matching what github_agent.py produced in Phase 1.
    """
    github = github or {}
    analysis = github.get("gpt_analysis") or {}
    return {
        "profile_found": github.get("profile_found", False),
        "repos_analyzed": [r.get("name") for r in github.get("repositories_analyzed", [])],
        "strengths_evidenced": analysis.get("strengths_evidenced", []),
        "notable_code_areas": analysis.get("notable_code_areas", []),
    }


def _github_grounded_count(question_plan: dict[str, Any]) -> int:
    return sum(1 for q in question_plan.get("questions", []) if q.get("source") == "github")


def score_interview(
    *,
    candidate_name: str,
    role: str,
    interview_date: str,
    duration_seconds: int,
    competencies: list[str],
    transcript: list[dict[str, Any]],
    evaluation_history: list[dict[str, Any]],
    resume: dict[str, Any],
    github_evidence: dict[str, Any],
    question_plan: dict[str, Any],
    guardrail_flags: list[str] | None = None,
    cache_key: str = FINAL_SCORER_CACHE_KEY,
) -> dict[str, Any]:
    system_prompt = load_prompt("final_scorer.md")

    static_context = {
        "role": role,
        "competencies_to_score": competencies,
        "relevant_candidate_claims": _compact_resume_claims(resume),
        "relevant_github_evidence": _compact_github_evidence(github_evidence),
        "prior_guardrail_flags": guardrail_flags or [],
    }
    dynamic_suffix = {
        "per_answer_evaluations": evaluation_history,
        "transcript": transcript,  # kept last, as required
    }
    user_content = json.dumps(static_context, indent=2) + "\n\n" + json.dumps(dynamic_suffix, indent=2)

    raw, usage = structured_completion_with_usage(
        system_prompt=system_prompt,
        user_content=user_content,
        json_schema=_GPT_SCORECARD_SCHEMA,
        schema_name="final_scorecard_schema",
        temperature=0.0,
        prompt_cache_key=cache_key,
    )
    cache_metrics.record(
        model=DEFAULT_MODEL,
        purpose="final_scoring",
        input_tokens=usage["input_tokens"],
        cached_tokens=usage["cached_tokens"],
        output_tokens=usage["output_tokens"],
    )

    scorecard = {
        "candidate_name": candidate_name,
        "role": role,
        "interview_date": interview_date,
        "duration_seconds": duration_seconds,
        **raw,
        "github_grounded_questions_asked": _github_grounded_count(question_plan),
    }

    # Deterministic evidence guardrail — the only thing that decides
    # whether a score actually counts.
    scorecard = validate_scorecard_evidence(scorecard, transcript)
    return scorecard
