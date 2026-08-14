"""HITL gate: the graph genuinely pauses here until a recruiter approves,
edits, or rejects the question plan. Nothing downstream runs without this.
"""
from __future__ import annotations

from langgraph.types import interrupt

from src.nodes._helpers import build_question_queue, now_ms
from src.state import InterviewState


def hitl_approval(state: InterviewState) -> InterviewState:
    decision = interrupt(
        {
            "type": "hitl_question_plan_approval",
            "question_plan": state.get("question_plan"),
        }
    )
    action = (decision or {}).get("action", "reject")

    if action == "edit":
        edited = decision.get("edited_questions")
        if edited is not None:
            state["question_plan"]["questions"] = edited
        note = decision.get("notes", "recruiter edited the question plan")
        state.setdefault("plan_edits", []).append(note)
        action = "approve"  # an edit is an approval-with-changes

    if action == "approve":
        state["plan_approval_status"] = "approved"
        state["question_plan"]["approved_by_human"] = True
        state["question_plan"]["edits_made"] = state.get("plan_edits", [])
        state["question_queue"] = build_question_queue(state["question_plan"])
        state["status"] = "in_progress"
        state["start_time_ms"] = now_ms()
    else:
        state["plan_approval_status"] = "rejected"
        state["status"] = "rejected"

    return state


def route_after_hitl(state: InterviewState) -> str:
    return "intro" if state.get("plan_approval_status") == "approved" else "__end__"
