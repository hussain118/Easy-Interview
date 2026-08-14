"""End-to-end live tests against the real OpenRouter/GPT and GitHub REST
APIs. Skipped by default (costs quota + time) — run explicitly with:

    RUN_LIVE_TESTS=1 pytest tests/test_live_pipeline.py -v

Uses the synthetic inputs/jd.txt and inputs/resume.pdf fixtures.
"""
from pathlib import Path

import pytest

from src.agents.jd_parser import parse_jd
from src.agents.resume_parser import extract_pdf_text, parse_resume
from src.agents.github_agent import build_github_profile
from src.agents.gap_analysis import run_gap_analysis
from src.agents.question_planner import plan_questions, validate_github_grounding

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.live
def test_jd_parser_live():
    jd_text = (ROOT / "inputs" / "jd.txt").read_text(encoding="utf-8")
    result = parse_jd(jd_text)
    assert result["role_title"]
    assert result["seniority"] in {"intern", "junior", "mid", "senior", "lead", "unspecified"}
    assert len(result["must_haves"]) > 0


@pytest.mark.live
def test_resume_parser_live():
    text = extract_pdf_text(ROOT / "inputs" / "resume.pdf")
    result = parse_resume(text)
    assert result["candidate_name"]
    assert "github.com" in result["links"]["github"]


@pytest.mark.live
def test_github_agent_live(tmp_path):
    resume_json = {"links": {"github": "https://github.com/encode"}, "skills": ["Python"]}
    jd_json = {"must_haves": ["Python"], "nice_to_haves": []}
    out_path = tmp_path / "github.json"
    result = build_github_profile(resume_json, jd_json, out_path)
    assert result["profile_found"] is True
    assert len(result["repositories_analyzed"]) > 0
    assert out_path.exists()


@pytest.mark.live
def test_full_pipeline_produces_valid_grounded_plan(tmp_path):
    jd_text = (ROOT / "inputs" / "jd.txt").read_text(encoding="utf-8")
    jd_json = parse_jd(jd_text)

    resume_text = extract_pdf_text(ROOT / "inputs" / "resume.pdf")
    resume_json = parse_resume(resume_text)

    github_json = build_github_profile(resume_json, jd_json, tmp_path / "github.json")

    gap_json = run_gap_analysis(jd_json, resume_json, github_json)

    plan = plan_questions(jd_json, resume_json, github_json, gap_json)
    problems = validate_github_grounding(plan, github_json)
    assert problems == [], problems
    assert len(plan["questions"]) == 12
