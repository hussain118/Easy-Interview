"""Live test: real GPT final scorer against a real transcript (built via
the real graph + real evaluator, no mocking), with the evidence guardrail
applied for real. Skipped by default: RUN_LIVE_TESTS=1 pytest
tests/test_scorer_live.py -v -s
"""
from __future__ import annotations

import pytest

from src.agents.scorer import score_interview
from src.graph import build_graph, build_initial_state, get_sqlite_checkpointer
from src.realtime.mock_adapter import MockRealtimeAdapter
from src.realtime.session_runner import make_adapter_resume_fn, run_full_session


def _q(id_, source, comp, text, ref=""):
    return {
        "id": id_, "text": text, "competency": comp, "source": source,
        "source_reference": ref, "difficulty": "medium", "follow_up_triggers": [],
    }


@pytest.mark.live
def test_real_scorer_produces_valid_schema_and_verified_evidence(tmp_path):
    plan = {
        "questions": [
            _q("q1", "resume", "backend", "Tell me about your REST API project."),
            _q("q2", "jd", "rag", "How would you design a RAG pipeline?"),
        ],
        "approved_by_human": False, "edits_made": [],
    }
    jd = {"competencies": [{"name": "backend", "description": "x"}, {"name": "rag", "description": "y"}]}
    resume = {"claims": ["Built a FastAPI service with JWT auth and Postgres for storage."]}
    state = build_initial_state(
        interview_id="score-live-test", candidate_name="Test Candidate", role_title="Junior AI Engineer",
        jd=jd, resume=resume, github_evidence={"profile_found": False}, question_plan=plan,
    )

    checkpointer = get_sqlite_checkpointer(tmp_path / "cp.sqlite")
    graph = build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "score-live-test"}}

    answers = [
        "I built a FastAPI service with JWT auth and Postgres for storage, deployed on Render.",
        "I'd chunk documents by paragraph with overlap, embed with a sentence-transformer model, and retrieve top-k from a vector store.",
        "No questions from me.",
    ]
    adapter = MockRealtimeAdapter(scripted_answers=answers)
    resume_fn = make_adapter_resume_fn(adapter, {"action": "approve"})
    result = run_full_session(graph, config, state, resume_fn)
    assert result["status"] == "completed"

    scorecard = score_interview(
        candidate_name="Test Candidate",
        role="Junior AI Engineer",
        interview_date="2026-01-01",
        duration_seconds=60,
        competencies=["backend", "rag"],
        transcript=result["transcript"],
        evaluation_history=result["evaluation_history"],
        resume=resume,
        github_evidence={"profile_found": False},
        question_plan=plan,
        guardrail_flags=result.get("guardrail_flags", []),
    )

    # Schema shape
    for key in (
        "candidate_name", "role", "interview_date", "duration_seconds", "competencies",
        "overall_score", "recommendation", "recommendation_reasoning", "strengths",
        "concerns", "guardrail_flags", "github_grounded_questions_asked",
    ):
        assert key in scorecard
    assert scorecard["recommendation"] in {"hire", "no_hire", "borderline"}
    assert scorecard["github_grounded_questions_asked"] == 0  # no github-sourced question in this plan

    # Every surviving competency's evidence_quote must genuinely be in the transcript
    transcript_text = " ".join(t["text"] for t in result["transcript"]).lower()
    for comp in scorecard["competencies"]:
        assert comp["evidence_quote"].lower() in transcript_text
