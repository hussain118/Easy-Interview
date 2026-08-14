"""GPT-based question planning -> output/prep/question_plan.json

Schema is fixed by the assignment spec (§6) and must not be altered.
Includes a deterministic Python guardrail that rejects any "github"
sourced question whose source_reference does not match real evidence
pulled by github_agent — no fake GitHub-grounded questions.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.providers.openai_client import load_prompt, structured_completion

QUESTION_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "competency": {"type": "string"},
                    "source": {
                        "type": "string",
                        "enum": ["jd", "resume", "github", "scenario"],
                    },
                    "source_reference": {"type": "string"},
                    "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
                    "follow_up_triggers": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "id",
                    "text",
                    "competency",
                    "source",
                    "source_reference",
                    "difficulty",
                    "follow_up_triggers",
                ],
                "additionalProperties": False,
            },
        },
        "approved_by_human": {"type": "boolean"},
        "edits_made": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["questions", "approved_by_human", "edits_made"],
    "additionalProperties": False,
}

MIN_GITHUB_GROUNDED_QUESTIONS = 3


class GitHubGroundingError(ValueError):
    """Raised when github-sourced questions cannot be matched to real evidence."""


def _collect_valid_github_tokens(github_json: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for repo in github_json.get("repositories_analyzed") or []:
        if repo.get("name"):
            tokens.add(repo["name"].lower())
        if repo.get("full_name"):
            tokens.add(repo["full_name"].lower())
        for commit in repo.get("recent_commits") or []:
            if commit.get("sha"):
                tokens.add(commit["sha"].lower())
        for sample_file in repo.get("sample_files") or []:
            if sample_file.get("path"):
                tokens.add(sample_file["path"].lower())
        tokens.add("readme")
    return tokens


def validate_github_grounding(
    question_plan: dict[str, Any], github_json: dict[str, Any]
) -> list[str]:
    """Returns a list of problems found (empty list = valid)."""
    problems: list[str] = []
    github_questions = [q for q in question_plan["questions"] if q["source"] == "github"]

    if len(github_questions) < MIN_GITHUB_GROUNDED_QUESTIONS:
        if github_json.get("profile_found") and github_json.get("repositories_analyzed"):
            problems.append(
                f"Only {len(github_questions)} github-sourced questions, "
                f"need >= {MIN_GITHUB_GROUNDED_QUESTIONS} when GitHub evidence exists."
            )

    valid_tokens = _collect_valid_github_tokens(github_json)
    for q in github_questions:
        ref = (q.get("source_reference") or "").lower()
        if not valid_tokens or not any(tok in ref for tok in valid_tokens):
            problems.append(
                f"Question {q['id']} source_reference '{q['source_reference']}' "
                "does not match any real repo/commit/README from github.json evidence."
            )
    return problems


def plan_questions(
    jd_json: dict[str, Any],
    resume_json: dict[str, Any],
    github_json: dict[str, Any],
    gap_analysis_json: dict[str, Any],
    retry_note: str | None = None,
) -> dict[str, Any]:
    system_prompt = load_prompt("question_planner_v2.md")
    user_payload: dict[str, Any] = {
        "job_description": jd_json,
        "resume": resume_json,
        "github_evidence": github_json,
        "gap_analysis": gap_analysis_json,
    }
    if retry_note:
        user_payload["regeneration_instruction"] = retry_note
    plan = structured_completion(
        system_prompt=system_prompt,
        user_content=json.dumps(user_payload, indent=2),
        json_schema=QUESTION_PLAN_SCHEMA,
        schema_name="question_plan_schema",
    )
    plan["approved_by_human"] = False
    plan["edits_made"] = []
    return plan


def plan_questions_to_file(
    jd_json: dict[str, Any],
    resume_json: dict[str, Any],
    github_json: dict[str, Any],
    gap_analysis_json: dict[str, Any],
    output_path: Path,
    *,
    enforce_grounding: bool = True,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Generates the plan and validates GitHub grounding. If the guardrail
    finds a shortfall (e.g. model variability produced only 1-2 real
    github-sourced questions instead of >=3), retries once with an explicit
    correction note before giving up. See prompts/ITERATION_NOTES.md.
    """
    plan = plan_questions(jd_json, resume_json, github_json, gap_analysis_json)
    problems = validate_github_grounding(plan, github_json)

    attempt = 1
    while problems and enforce_grounding and attempt < max_attempts:
        attempt += 1
        retry_note = (
            "Your previous attempt failed this hard requirement: "
            + "; ".join(problems)
            + ". Regenerate the full 12-question plan, this time ensuring "
            "at least 3 questions have source=github with a source_reference "
            "that names a real repo/file/commit from the github_evidence given."
        )
        plan = plan_questions(
            jd_json, resume_json, github_json, gap_analysis_json, retry_note=retry_note
        )
        problems = validate_github_grounding(plan, github_json)

    if problems and enforce_grounding:
        raise GitHubGroundingError("; ".join(problems))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return plan
