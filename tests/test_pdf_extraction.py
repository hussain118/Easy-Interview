from pathlib import Path

from src.agents.resume_parser import extract_pdf_text

RESUME_PDF = Path(__file__).resolve().parent.parent / "inputs" / "resume.pdf"


def test_resume_pdf_exists():
    assert RESUME_PDF.exists(), "inputs/resume.pdf fixture is missing"


def test_extract_pdf_text_returns_nontrivial_text():
    text = extract_pdf_text(RESUME_PDF)
    assert len(text.strip()) > 100


def test_extract_pdf_text_contains_known_content():
    text = extract_pdf_text(RESUME_PDF)
    assert "github.com/encode" in text
    assert "SKILLS" in text
