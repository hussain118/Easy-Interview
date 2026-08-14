"""Tests the deterministic Python guardrail that rejects fabricated
GitHub-grounded questions — no LLM calls involved."""
from src.agents.question_planner import validate_github_grounding

GITHUB_EVIDENCE = {
    "profile_found": True,
    "repositories_analyzed": [
        {
            "name": "rag-pipeline",
            "full_name": "candidate/rag-pipeline",
            "recent_commits": [{"sha": "a1b2c3d4e5"}],
            "sample_files": [{"path": "chunker.py"}],
        }
    ],
}


def _plan_with_questions(questions):
    return {"questions": questions, "approved_by_human": False, "edits_made": []}


def test_rejects_fabricated_repo_reference():
    plan = _plan_with_questions(
        [
            {
                "id": "q1",
                "text": "...",
                "competency": "backend",
                "source": "github",
                "source_reference": "repo:totally-made-up-repo, file:fake.py",
                "difficulty": "medium",
                "follow_up_triggers": [],
            }
        ]
    )
    problems = validate_github_grounding(plan, GITHUB_EVIDENCE)
    assert problems, "a fabricated repo reference must be flagged"


def test_accepts_real_repo_reference():
    plan = _plan_with_questions(
        [
            {
                "id": f"q{i}",
                "text": "...",
                "competency": "backend",
                "source": "github",
                "source_reference": "repo:rag-pipeline, file:chunker.py",
                "difficulty": "medium",
                "follow_up_triggers": [],
            }
            for i in range(1, 4)
        ]
    )
    problems = validate_github_grounding(plan, GITHUB_EVIDENCE)
    assert problems == []


def test_flags_insufficient_github_question_count():
    plan = _plan_with_questions(
        [
            {
                "id": "q1",
                "text": "...",
                "competency": "backend",
                "source": "github",
                "source_reference": "repo:rag-pipeline, commit:a1b2c3d4e5",
                "difficulty": "medium",
                "follow_up_triggers": [],
            }
        ]
    )
    problems = validate_github_grounding(plan, GITHUB_EVIDENCE)
    assert any("Only 1 github-sourced" in p for p in problems)


def test_no_github_evidence_does_not_require_github_questions():
    empty_evidence = {"profile_found": False, "repositories_analyzed": []}
    plan = _plan_with_questions(
        [
            {
                "id": "q1",
                "text": "...",
                "competency": "backend",
                "source": "resume",
                "source_reference": "some claim",
                "difficulty": "easy",
                "follow_up_triggers": [],
            }
        ]
    )
    problems = validate_github_grounding(plan, empty_evidence)
    assert problems == []
