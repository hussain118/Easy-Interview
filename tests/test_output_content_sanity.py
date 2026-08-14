"""Sanity checks against the already-generated PREP outputs for the
synthetic test fixture: resume parsing shouldn't hallucinate fields beyond
what's in the fixture, and GitHub evidence must be real (real URLs under
the actual account), never fabricated.
"""
import json
from pathlib import Path

import pytest

PREP_DIR = Path(__file__).resolve().parent.parent / "output" / "prep"


def _load_or_skip(name):
    path = PREP_DIR / name
    if not path.exists():
        pytest.skip(f"{path} not generated yet — run `python run_prep.py` first")
    return json.loads(path.read_text(encoding="utf-8"))


def test_resume_did_not_hallucinate_github_link():
    resume = _load_or_skip("resume.json")
    assert resume["links"]["github"] in (
        "https://github.com/encode",
        "github.com/encode",
    )


def test_github_evidence_urls_are_real_and_under_the_right_account():
    github = _load_or_skip("github.json")
    assert github["profile_found"] is True
    assert github["username"] == "encode"
    for repo in github["repositories_analyzed"]:
        assert repo["url"].startswith("https://github.com/encode/")


def test_github_questions_reference_repos_that_were_actually_analyzed():
    plan = _load_or_skip("question_plan.json")
    github = _load_or_skip("github.json")
    analyzed_names = {r["name"].lower() for r in github["repositories_analyzed"]}

    for q in plan["questions"]:
        if q["source"] != "github":
            continue
        ref = q["source_reference"].lower()
        assert any(name in ref for name in analyzed_names), (
            f"question {q['id']} references '{q['source_reference']}' "
            "which doesn't match any analyzed repo"
        )
