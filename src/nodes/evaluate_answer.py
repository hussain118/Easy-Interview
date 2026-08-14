"""Calls the GPT evaluator on the candidate's last answer, then decides the
next action deterministically. This is the only place GPT output can
influence graph control flow, and only through the validated "quality"
enum — never raw LLM text.

All decision state (next_action, follow_up_count, difficulty) is set HERE,
inside the node, because only a node's return value is persisted by
LangGraph — mutations made inside a conditional-edge (path) function are
NOT saved to the checkpoint. route_after_evaluation below is therefore a
pure, read-only function: it only decides where to go, never what to do.
"""
from __future__ import annotations

from src.agents.evaluator import SILENCE_EVALUATION, evaluate_answer
from src.nodes._helpers import MAX_FOLLOW_UPS, time_exceeded
from src.state import InterviewState

DIFFICULTY_LADDER = ["easy", "medium", "hard"]


def _bump_difficulty(current: str) -> str:
    idx = DIFFICULTY_LADDER.index(current) if current in DIFFICULTY_LADDER else 1
    return DIFFICULTY_LADDER[min(idx + 1, len(DIFFICULTY_LADDER) - 1)]


def evaluate_answer_node(state: InterviewState) -> InterviewState:
    answer = (state.get("current_answer") or "").strip()
    question = state.get("current_question") or {}

    if not answer:
        evaluation = dict(SILENCE_EVALUATION)
    else:
        prior_turns = state.get("transcript", [])[-4:]
        evaluation = evaluate_answer(
            question_text=question.get("text", ""),
            competency=question.get("competency", ""),
            difficulty=state.get("difficulty", "medium"),
            source_reference=question.get("source_reference", ""),
            candidate_answer=answer,
            prior_turns=prior_turns,
        )
    state["last_evaluation"] = evaluation

    topic = state.get("current_phase", "")
    quality = evaluation["quality"]
    follow_ups = state.setdefault("follow_up_count", {})
    count = follow_ups.get(topic, 0)

    def resolved(next_count: int, action: str | None) -> None:
        follow_ups[topic] = next_count
        state["next_action"] = action

    if quality == "strong":
        state["difficulty"] = _bump_difficulty(state.get("difficulty", "medium"))
        resolved(0, None)
    elif quality == "good":
        resolved(0, None)
    elif count >= MAX_FOLLOW_UPS:
        resolved(0, None)  # cap reached — move on regardless of quality
    elif quality == "bluff":
        resolved(count + 1, "verify")
    elif quality == "shallow":
        resolved(count + 1, "follow_up")
    elif quality in ("off_topic", "unclear"):
        resolved(count + 1, "recovery")
    else:
        resolved(0, None)

    return state


def route_after_evaluation(state: InterviewState) -> str:
    """Pure/read-only: no state mutation here (see module docstring)."""
    if time_exceeded(state):
        return "wrap_up"
    return state.get("current_phase", "resume_probe")
