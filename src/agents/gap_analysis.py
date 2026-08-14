"""GPT-based gap analysis: resume claim vs JD need vs GitHub evidence.

Not one of the exact fixed output paths in the spec, but saved to
output/prep/gap_analysis.json as a reference artifact since it is a
required PREP workflow step and grounds the question planner.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.providers.openai_client import load_prompt, structured_completion

GAP_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "matched_competencies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "competency": {"type": "string"},
                    "evidence": {"type": "string"},
                    "source": {"type": "string", "enum": ["resume", "github", "both"]},
                },
                "required": ["competency", "evidence", "source"],
                "additionalProperties": False,
            },
        },
        "gaps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "competency": {"type": "string"},
                    "concern": {"type": "string"},
                },
                "required": ["competency", "concern"],
                "additionalProperties": False,
            },
        },
        "claims_to_verify": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "github_status": {
                        "type": "string",
                        "enum": ["supported", "contradicted", "unverifiable"],
                    },
                    "note": {"type": "string"},
                },
                "required": ["claim", "github_status", "note"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["matched_competencies", "gaps", "claims_to_verify"],
    "additionalProperties": False,
}


def run_gap_analysis(
    jd_json: dict[str, Any], resume_json: dict[str, Any], github_json: dict[str, Any]
) -> dict[str, Any]:
    system_prompt = load_prompt("gap_analysis_v1.md")
    user_content = json.dumps(
        {"job_description": jd_json, "resume": resume_json, "github_evidence": github_json},
        indent=2,
    )
    return structured_completion(
        system_prompt=system_prompt,
        user_content=user_content,
        json_schema=GAP_ANALYSIS_SCHEMA,
        schema_name="gap_analysis_schema",
    )


def run_gap_analysis_to_file(
    jd_json: dict[str, Any],
    resume_json: dict[str, Any],
    github_json: dict[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    result = run_gap_analysis(jd_json, resume_json, github_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
