"""Lets the candidate ask the interviewer a question before wrap-up."""
from __future__ import annotations

from langgraph.types import interrupt

from src.nodes._helpers import append_transcript_once
from src.state import InterviewState

NODE = "candidate_questions"


def candidate_questions(state: InterviewState) -> InterviewState:
    state["current_phase"] = NODE
    state["current_node"] = NODE

    prompt_text = "Before we wrap up — do you have any questions for me about the role or the team?"
    append_transcript_once(state, "agent", prompt_text, NODE)

    answer = interrupt({"type": "await_candidate_answer", "node": NODE, "question": prompt_text})
    answer = answer or ""
    append_transcript_once(state, "candidate", answer, NODE)

    ack = "Good question — the recruiting team will follow up on that after the interview."
    append_transcript_once(state, "agent", ack, NODE)
    return state
