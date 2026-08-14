"""Greets the candidate by name and discloses the AI, per spec requirement #1."""
from __future__ import annotations

from src.nodes._helpers import append_transcript_once, guarded_question_text
from src.state import InterviewState


def intro(state: InterviewState) -> InterviewState:
    name = state.get("candidate_name") or "there"
    role = state.get("role_title") or "this role"
    text = (
        f"Hi {name}, thanks for joining. I'm an AI interviewer conducting this "
        f"interview for the {role} position — to be transparent, you're speaking "
        "with an AI, not a human. We'll spend some time on your background, the "
        "role, and your projects. Let's get started."
    )
    text = guarded_question_text(state, text)
    append_transcript_once(state, "agent", text, "intro")
    state["current_phase"] = "intro"
    state["current_node"] = "intro"
    state["difficulty"] = state.get("difficulty") or "medium"
    state.setdefault("follow_up_count", {})
    state.setdefault("guardrail_flags", [])
    return state
