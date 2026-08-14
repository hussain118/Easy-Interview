"""Closing remarks. No further candidate interaction."""
from __future__ import annotations

from src.nodes._helpers import append_transcript_once
from src.state import InterviewState

NODE = "wrap_up"


def wrap_up(state: InterviewState) -> InterviewState:
    state["current_phase"] = NODE
    state["current_node"] = NODE
    name = state.get("candidate_name") or "there"
    text = (
        f"That's all the questions I have, {name}. Thanks so much for your time "
        "today — we'll be in touch with next steps soon."
    )
    append_transcript_once(state, "agent", text, NODE)
    return state
