"""Resume PDF extraction + GPT-based structuring -> output/prep/resume.json"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pdfplumber
from pypdf import PdfReader

from src.providers.openai_client import load_prompt, structured_completion

RESUME_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "candidate_name": {"type": "string"},
        "email": {"type": "string"},
        "phone": {"type": "string"},
        "location": {"type": "string"},
        "links": {
            "type": "object",
            "properties": {
                "github": {"type": "string"},
                "linkedin": {"type": "string"},
                "portfolio": {"type": "string"},
            },
            "required": ["github", "linkedin", "portfolio"],
            "additionalProperties": False,
        },
        "summary": {"type": "string"},
        "skills": {"type": "array", "items": {"type": "string"}},
        "roles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "company": {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["title", "company", "start_date", "end_date", "description"],
                "additionalProperties": False,
            },
        },
        "projects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "technologies": {"type": "array", "items": {"type": "string"}},
                    "link": {"type": "string"},
                },
                "required": ["name", "description", "technologies", "link"],
                "additionalProperties": False,
            },
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "institution": {"type": "string"},
                    "degree": {"type": "string"},
                    "field": {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                },
                "required": ["institution", "degree", "field", "start_date", "end_date"],
                "additionalProperties": False,
            },
        },
        "claims": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "candidate_name",
        "email",
        "phone",
        "location",
        "links",
        "summary",
        "skills",
        "roles",
        "projects",
        "education",
        "claims",
    ],
    "additionalProperties": False,
}


def extract_pdf_text(pdf_path: Path) -> str:
    """Extract text from a resume PDF. Tries pdfplumber first (better layout
    handling for messy/multi-column resumes), falls back to pypdf if that
    yields little or no text (e.g. a plain single-column PDF or a
    pdfplumber failure).
    """
    text_parts: list[str] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if page_text:
                    text_parts.append(page_text)
    except Exception:
        text_parts = []

    text = "\n".join(text_parts).strip()
    if len(text) >= 40:
        return text

    reader = PdfReader(str(pdf_path))
    fallback_parts = [page.extract_text() or "" for page in reader.pages]
    fallback_text = "\n".join(fallback_parts).strip()

    return fallback_text if len(fallback_text) > len(text) else text


def parse_resume(resume_text: str) -> dict[str, Any]:
    system_prompt = load_prompt("resume_parser_v1.md")
    return structured_completion(
        system_prompt=system_prompt,
        user_content=resume_text,
        json_schema=RESUME_SCHEMA,
        schema_name="resume_schema",
    )


def parse_resume_file(pdf_path: Path, output_path: Path) -> dict[str, Any]:
    resume_text = extract_pdf_text(pdf_path)
    if len(resume_text.strip()) < 20:
        raise ValueError(
            f"Could not extract usable text from {pdf_path}. "
            "The PDF may be a scanned image without an OCR text layer."
        )
    result = parse_resume(resume_text)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
