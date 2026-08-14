"""Verifies the mechanism the live worker uses to mark a transcript turn
as interrupted on barge-in: graph.update_state() correctly patches the
last agent turn without touching anything else. No network calls.
"""
from __future__ import annotations

from langgraph.types import Command

from src.graph import build_graph, build_initial_state, get_sqlite_checkpointer


def _mark_last_agent_turn_interrupted(graph, config):
    snapshot = graph.get_state(config)
    transcript = list(snapshot.values.get("transcript", []))
    for turn in reversed(transcript):
        if turn["speaker"] == "agent":
            turn["interrupted"] = True
            break
    graph.update_state(config, {"transcript": transcript})


def test_update_state_marks_last_agent_turn_interrupted(tmp_path):
    checkpointer = get_sqlite_checkpointer(tmp_path / "cp.sqlite")
    graph = build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "barge-in-test"}}

    plan = {
        "questions": [
            {
                "id": "q1", "text": "Tell me about a project.", "competency": "backend",
                "source": "resume", "source_reference": "", "difficulty": "medium",
                "follow_up_triggers": [],
            }
        ],
        "approved_by_human": False,
        "edits_made": [],
    }
    state = build_initial_state(
        interview_id="x", candidate_name="Test", role_title="role",
        jd={}, resume={}, github_evidence={}, question_plan=plan,
    )
    graph.invoke(state, config=config)
    graph.invoke(Command(resume={"action": "approve"}), config=config)

    before = graph.get_state(config).values["transcript"]
    assert all(t["interrupted"] is False for t in before)

    _mark_last_agent_turn_interrupted(graph, config)

    after = graph.get_state(config).values["transcript"]
    agent_turns = [t for t in after if t["speaker"] == "agent"]
    assert agent_turns[-1]["interrupted"] is True
    # only the last agent turn changed — everything else untouched
    assert agent_turns[0]["interrupted"] is False
