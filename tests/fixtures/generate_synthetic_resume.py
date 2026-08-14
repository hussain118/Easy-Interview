"""Generates inputs/resume.pdf: a minimal SYNTHETIC resume used only to
technically test the PREP pipeline (PDF extraction -> GPT structuring ->
GitHub grounding) before a real candidate resume is supplied.

The GitHub link points to https://github.com/encode — a real public GitHub
ORGANIZATION account (maintainers of httpx/starlette/uvicorn), chosen so
the pipeline exercises the real GitHub REST API against genuinely
substantive repos without attributing any real individual's personal
identity/work to this fictional candidate.

Run: python tests/fixtures/generate_synthetic_resume.py
"""
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

OUTPUT_PATH = Path(__file__).resolve().parent.parent.parent / "inputs" / "resume.pdf"

LINES = [
    "Test Candidate (SYNTHETIC — technical test fixture, not a real person)",
    "Email: test.candidate@example.com | Phone: +92-300-0000000",
    "Location: Karachi, Pakistan",
    "GitHub: https://github.com/encode | LinkedIn: linkedin.com/in/testcandidate",
    "",
    "SUMMARY",
    "Junior software engineer with 1 year of experience building small",
    "Python backend services and experimenting with LLM-based tools.",
    "",
    "SKILLS",
    "Python, REST APIs, Git, SQL, basic LangChain, Docker basics",
    "",
    "EXPERIENCE",
    "Software Engineer Intern - Sample Tech Co.  (Jun 2024 - Dec 2024)",
    "- Built a small REST API in Python for internal tooling",
    "- Wrote unit tests and fixed bugs reported by QA",
    "- Collaborated with a team of 3 using Git for version control",
    "",
    "PROJECTS",
    "Hello-World Demo App",
    "- A demo repository used to learn GitHub workflows and pull requests",
    "- Technologies: Git, GitHub",
    "",
    "EDUCATION",
    "B.S. Computer Science - Sample University (2020 - 2024)",
]


def generate() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUTPUT_PATH), pagesize=LETTER)
    width, height = LETTER
    text_obj = c.beginText(50, height - 50)
    text_obj.setFont("Helvetica", 11)
    for line in LINES:
        text_obj.textLine(line)
    c.drawText(text_obj)
    c.showPage()
    c.save()
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    generate()
