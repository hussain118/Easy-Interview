"""GPT-based job description parser -> output/prep/jd.json"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.providers.openai_client import load_prompt, structured_completion

JD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "role_title": {"type": "string"},
        "company": {"type": "string"},
        "location": {"type": "string"},
        "employment_type": {"type": "string"},
        "seniority": {
            "type": "string",
            "enum": ["intern", "junior", "mid", "senior", "lead", "unspecified"],
        },
        "years_experience_required": {"type": "string"},
        "must_haves": {"type": "array", "items": {"type": "string"}},
        "nice_to_haves": {"type": "array", "items": {"type": "string"}},
        "competencies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "description"],
                "additionalProperties": False,
            },
        },
        "responsibilities": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "role_title",
        "company",
        "location",
        "employment_type",
        "seniority",
        "years_experience_required",
        "must_haves",
        "nice_to_haves",
        "competencies",
        "responsibilities",
    ],
    "additionalProperties": False,
}


def parse_jd(jd_text: str) -> dict[str, Any]:
    system_prompt = load_prompt("jd_parser_v1.md")
    return structured_completion(
        system_prompt=system_prompt,
        user_content=jd_text,
        json_schema=JD_SCHEMA,
        schema_name="jd_schema",
    )


def parse_jd_file(jd_path: Path, output_path: Path) -> dict[str, Any]:
    jd_text = jd_path.read_text(encoding="utf-8")
    result = parse_jd(jd_text)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
