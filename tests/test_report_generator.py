"""Tests for src/agents/report_generator.py: redaction correctness and
real PDF generation. No network calls (pure reportlab).
"""
from __future__ import annotations

from src.agents.report_generator import _redact, _redact_scorecard, generate_report_pdf

SAMPLE_SCORECARD = {
    "candidate_name": "Test Candidate",
    "role": "Junior AI Engineer",
    "interview_date": "2026-08-14",
    "duration_seconds": 480,
    "competencies": [
        {
            "name": "backend", "score": 4, "confidence": 0.8,
            "evidence_quote": "I built a FastAPI service with JWT auth.",
            "reasoning": "Specific and grounded.",
        }
    ],
    "overall_score": 4.0,
    "recommendation": "hire",
    "recommendation_reasoning": "Strong technical depth.",
    "strengths": ["Clear communication."],
    "concerns": [],
    "guardrail_flags": [],
    "github_grounded_questions_asked": 2,
}


def test_redact_phone_number():
    assert "[redacted]" in _redact("Call me at 555-123-4567 anytime.")


def test_redact_national_id_pattern():
    assert "[redacted]" in _redact("My CNIC is 12345-1234567-1.")


def test_redact_address_pattern():
    assert "[redacted]" in _redact("I live at 123 Main Street.")


def test_redact_does_not_touch_plain_technical_text():
    text = "I chunked by paragraph with 200-token overlap."
    assert _redact(text) == text


def test_redact_scorecard_does_not_corrupt_iso_date():
    redacted = _redact_scorecard(SAMPLE_SCORECARD)
    assert redacted["interview_date"] == "2026-08-14"  # must NOT be redacted


def test_redact_scorecard_does_not_touch_scores_or_counts():
    redacted = _redact_scorecard(SAMPLE_SCORECARD)
    assert redacted["duration_seconds"] == 480
    assert redacted["overall_score"] == 4.0
    assert redacted["github_grounded_questions_asked"] == 2


def test_redact_scorecard_redacts_pii_in_free_text_fields():
    scorecard = dict(SAMPLE_SCORECARD)
    scorecard["recommendation_reasoning"] = "Reach them at 555-123-4567 for follow-up."
    redacted = _redact_scorecard(scorecard)
    assert "555-123-4567" not in redacted["recommendation_reasoning"]


def test_generate_report_pdf_creates_real_pdf_file(tmp_path):
    output_path = tmp_path / "report.pdf"
    generate_report_pdf(SAMPLE_SCORECARD, output_path)
    assert output_path.exists()
    assert output_path.read_bytes()[:5] == b"%PDF-"
    assert output_path.stat().st_size > 500


def test_generate_report_pdf_handles_empty_competencies(tmp_path):
    scorecard = dict(SAMPLE_SCORECARD)
    scorecard["competencies"] = []
    output_path = tmp_path / "report_empty.pdf"
    generate_report_pdf(scorecard, output_path)  # must not raise
    assert output_path.exists()
