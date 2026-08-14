"""Shared fixtures/helpers for graph tests. No network calls."""
from __future__ import annotations

from src.graph import build_graph, build_initial_state, get_sqlite_checkpointer


def make_question_plan() -> dict:
    def q(id_, source, comp, text, ref="", diff="medium"):
        return {
            "id": id_,
            "text": text,
            "competency": comp,
            "source": source,
            "source_reference": ref,
            "difficulty": diff,
            "follow_up_triggers": ["no specifics on scale"],
        }

    return {
        "questions": [
            q("q1", "resume", "backend", "Tell me about your REST API project."),
            q("q2", "resume", "testing", "How did you test that project?"),
            q("q3", "jd", "rag", "How would you design a RAG pipeline?"),
            q("q4", "jd", "git", "Walk me through your Git workflow."),
            q("q5", "github", "python", "Tell me about repo:foo", ref="repo:foo, file:main.py"),
            q("q6", "github", "python", "Tell me about commit abc123", ref="repo:foo, commit:abc123"),
            q("q7", "scenario", "debugging", "A production API is returning 500s — what do you do?"),
        ],
        "approved_by_human": False,
        "edits_made": [],
    }


def make_initial_state(interview_id: str = "test-interview") -> dict:
    return build_initial_state(
        interview_id=interview_id,
        candidate_name="Test Candidate",
        role_title="Junior AI Engineer",
        jd={"role_title": "Junior AI Engineer"},
        resume={"candidate_name": "Test Candidate"},
        github_evidence={"profile_found": True},
        question_plan=make_question_plan(),
    )


def make_graph_and_config(tmp_path, thread_id: str = "t1"):
    checkpointer = get_sqlite_checkpointer(tmp_path / "checkpoints.sqlite")
    graph = build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": thread_id}}
    return graph, config
