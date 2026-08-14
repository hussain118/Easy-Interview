"""Deterministic evidence guardrail: no competency score survives without
a real, verbatim transcript quote. No network calls.
"""
from __future__ import annotations

from src.guardrails.evidence_check import quote_found_in_transcript, validate_scorecard_evidence

TRANSCRIPT = [
    {"speaker": "agent", "text": "Tell me about your REST API project.", "timestamp_ms": 0, "node": "resume_probe", "interrupted": False},
    {"speaker": "candidate", "text": "I built a FastAPI service with JWT auth and Postgres for storage.", "timestamp_ms": 1, "node": "resume_probe", "interrupted": False},
]


def test_quote_found_exact():
    assert quote_found_in_transcript("I built a FastAPI service with JWT auth and Postgres for storage.", TRANSCRIPT)


def test_quote_found_case_and_whitespace_insensitive():
    assert quote_found_in_transcript("  i built a FASTAPI service   with jwt auth", TRANSCRIPT)


def test_quote_partial_substring_found():
    assert quote_found_in_transcript("JWT auth and Postgres", TRANSCRIPT)


def test_quote_not_found_fabricated():
    assert not quote_found_in_transcript("I scaled the system to 10 million users.", TRANSCRIPT)


def test_quote_empty_not_found():
    assert not quote_found_in_transcript("", TRANSCRIPT)


def test_validate_scorecard_evidence_keeps_valid_rejects_fabricated():
    scorecard = {
        "competencies": [
            {
                "name": "backend", "score": 4, "confidence": 0.8,
                "evidence_quote": "I built a FastAPI service with JWT auth and Postgres for storage.",
                "reasoning": "Specific and grounded.",
            },
            {
                "name": "scale", "score": 5, "confidence": 0.9,
                "evidence_quote": "I scaled the system to 10 million users.",
                "reasoning": "Fabricated — not actually said.",
            },
        ],
        "guardrail_flags": [],
    }
    result = validate_scorecard_evidence(scorecard, TRANSCRIPT)
    assert [c["name"] for c in result["competencies"]] == ["backend"]
    assert any("scale" in f for f in result["guardrail_flags"])
    assert result["overall_score"] == 4.0


def test_validate_scorecard_evidence_all_rejected_gives_zero_overall():
    scorecard = {
        "competencies": [
            {"name": "x", "score": 5, "confidence": 0.9, "evidence_quote": "never said this", "reasoning": "r"},
        ],
        "guardrail_flags": [],
    }
    result = validate_scorecard_evidence(scorecard, TRANSCRIPT)
    assert result["competencies"] == []
    assert result["overall_score"] == 0.0


def test_validate_scorecard_evidence_does_not_mutate_input():
    scorecard = {
        "competencies": [
            {"name": "x", "score": 5, "confidence": 0.9, "evidence_quote": "never said this", "reasoning": "r"},
        ],
        "guardrail_flags": [],
    }
    validate_scorecard_evidence(scorecard, TRANSCRIPT)
    assert len(scorecard["competencies"]) == 1  # original untouched
