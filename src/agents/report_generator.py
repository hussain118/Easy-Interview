"""output/scorecard.json -> output/report.pdf (reportlab, no LLM call).

Redacts anything that looks like a national ID, phone number, or a street
address pattern from every text field before it's written to the PDF —
defensive, since the scorecard shouldn't contain these anyway, but the
spec explicitly requires it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_PHONE_RE = re.compile(r"(?:\+?\d[\d\-\s()]{7,}\d)")
_ADDRESS_RE = re.compile(
    r"\b\d{1,5}\s+\w+(?:\s\w+){0,3}\s(?:street|st|avenue|ave|road|rd|lane|ln|block|sector)\b",
    re.IGNORECASE,
)
_NATIONAL_ID_RE = re.compile(r"\b\d{5}-\d{7}-\d\b")  # e.g. Pakistani CNIC format


def _redact(text: str) -> str:
    if not text:
        return text
    text = _NATIONAL_ID_RE.sub("[redacted]", text)
    text = _ADDRESS_RE.sub("[redacted]", text)
    text = _PHONE_RE.sub("[redacted]", text)
    return text


# Only free-text fields where a candidate's own words could contain PII
# are redacted — structured/deterministic fields (interview_date, scores,
# counts) are never run through the redaction regexes, since a plain ISO
# date or a "5/5" score can otherwise false-positive against a phone-number
# pattern (caught during testing — see prompts/ITERATION_NOTES.md).
_FREE_TEXT_SCORECARD_FIELDS = {
    "candidate_name", "recommendation_reasoning", "strengths", "concerns",
    "guardrail_flags", "evidence_quote", "reasoning",
}


def _redact_scorecard(scorecard: dict[str, Any]) -> dict[str, Any]:
    def walk(value, field_name: str | None):
        if isinstance(value, str):
            return _redact(value) if field_name in _FREE_TEXT_SCORECARD_FIELDS else value
        if isinstance(value, list):
            return [walk(v, field_name) for v in value]
        if isinstance(value, dict):
            return {k: walk(v, k) for k, v in value.items()}
        return value

    return walk(scorecard, None)


def generate_report_pdf(scorecard: dict[str, Any], output_path: Path) -> None:
    scorecard = _redact_scorecard(scorecard)
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    h2 = styles["Heading2"]
    body = styles["BodyText"]
    quote_style = ParagraphStyle("quote", parent=body, leftIndent=18, textColor="#333333", fontName="Helvetica-Oblique")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(output_path), pagesize=LETTER)
    story = []

    story.append(Paragraph("FirstRound Interview Scorecard", title_style))
    story.append(Spacer(1, 12))

    header_rows = [
        ["Candidate", scorecard.get("candidate_name", "")],
        ["Role", scorecard.get("role", "")],
        ["Interview date", scorecard.get("interview_date", "")],
        ["Duration", f"{scorecard.get('duration_seconds', 0)} seconds"],
        ["GitHub-grounded questions asked", str(scorecard.get("github_grounded_questions_asked", 0))],
        ["Overall score", str(scorecard.get("overall_score", ""))],
        ["Recommendation", scorecard.get("recommendation", "").upper()],
    ]
    table = Table(header_rows, colWidths=[2.2 * inch, 4.0 * inch])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, "#cccccc"),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 16))

    story.append(Paragraph("Recommendation reasoning", h2))
    story.append(Paragraph(scorecard.get("recommendation_reasoning", ""), body))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Competency scores", h2))
    for comp in scorecard.get("competencies", []):
        story.append(
            Paragraph(
                f"<b>{comp.get('name','')}</b> — score {comp.get('score','')}/5 "
                f"(confidence {comp.get('confidence','')})",
                body,
            )
        )
        story.append(Paragraph(f"&ldquo;{comp.get('evidence_quote','')}&rdquo;", quote_style))
        story.append(Paragraph(comp.get("reasoning", ""), body))
        story.append(Spacer(1, 8))

    if not scorecard.get("competencies"):
        story.append(Paragraph("No competency scores survived the evidence guardrail.", body))
        story.append(Spacer(1, 8))

    story.append(Paragraph("Strengths", h2))
    for s in scorecard.get("strengths", []) or ["(none noted)"]:
        story.append(Paragraph(f"• {s}", body))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Concerns", h2))
    for c in scorecard.get("concerns", []) or ["(none noted)"]:
        story.append(Paragraph(f"• {c}", body))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Guardrail flags", h2))
    for f in scorecard.get("guardrail_flags", []) or ["(none)"]:
        story.append(Paragraph(f"• {f}", body))

    doc.build(story)


def main() -> int:
    root = Path(__file__).resolve().parent.parent.parent
    scorecard_path = root / "output" / "scorecard.json"
    output_path = root / "output" / "report.pdf"
    if not scorecard_path.exists():
        print(f"{scorecard_path} not found — run run_scoring.py first.")
        return 1
    scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
    generate_report_pdf(scorecard, output_path)
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
