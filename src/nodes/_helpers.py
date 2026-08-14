"""Shared helpers for interview graph nodes. Not a node itself."""
from __future__ import annotations

import time
from typing import Any

from src.guardrails.banned_questions import SAFE_FALLBACK_QUESTION, check_question
from src.state import InterviewState

TOPIC_SEQUENCE = ["resume_probe", "jd_fit", "github_deepdive", "scenario"]
SOURCE_BY_TOPIC = {
    "resume_probe": "resume",
    "jd_fit": "jd",
    "github_deepdive": "github",
    "scenario": "scenario",
}
MAX_FOLLOW_UPS = 2
MAX_INTERVIEW_SECONDS = 1200  # safety net so a stuck interview jumps to wrap_up


def now_ms() -> int:
    return int(time.time() * 1000)


def append_transcript_once(
    state: InterviewState, speaker: str, text: str, node: str, interrupted: bool = False
) -> None:
    """Idempotent transcript append — guards against LangGraph re-running a
    node function from the top after an interrupt() resume.
    """
    transcript = state.setdefault("transcript", [])
    if transcript and transcript[-1]["speaker"] == speaker and transcript[-1]["text"] == text and transcript[-1]["node"] == node:
        return
    transcript.append(
        {
            "speaker": speaker,
            "text": text,
            "timestamp_ms": now_ms(),
            "node": node,
            "interrupted": interrupted,
        }
    )


def guarded_question_text(state: InterviewState, text: str) -> str:
    matched = check_question(text)
    if matched:
        state.setdefault("guardrail_flags", []).append(
            f"banned_question_blocked:{','.join(matched)}:'{text[:80]}'"
        )
        return SAFE_FALLBACK_QUESTION
    return text


def build_question_queue(question_plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Groups approved plan questions by interview topic node, preserving
    each group's relative order, in TOPIC_SEQUENCE order.
    """
    questions = question_plan.get("questions", [])
    queue: list[dict[str, Any]] = []
    for topic in TOPIC_SEQUENCE:
        source = SOURCE_BY_TOPIC[topic]
        for q in questions:
            if q.get("source") == source:
                queue.append({**q, "node": topic})
    return queue


def pop_next_for_topic(state: InterviewState, topic: str) -> dict[str, Any] | None:
    queue = state.get("question_queue", [])
    if queue and queue[0].get("node") == topic:
        return queue.pop(0)
    return None


def next_topic_after(topic: str) -> str:
    if topic not in TOPIC_SEQUENCE:
        return "candidate_questions"
    idx = TOPIC_SEQUENCE.index(topic)
    if idx + 1 < len(TOPIC_SEQUENCE):
        return TOPIC_SEQUENCE[idx + 1]
    return "candidate_questions"


def time_exceeded(state: InterviewState) -> bool:
    start = state.get("start_time_ms")
    if not start:
        return False
    return (now_ms() - start) / 1000.0 > MAX_INTERVIEW_SECONDS


def generate_probe_question(state: InterviewState, action: str) -> str:
    """Deterministic (non-LLM) probe text generation — cheap, testable, and
    keeps question *generation* separate from answer *evaluation*.
    """
    current = state.get("current_question") or {}
    triggers = current.get("follow_up_triggers") or []
    ref = current.get("source_reference", "")
    reason = (state.get("last_evaluation") or {}).get("reason", "")

    if action == "follow_up":
        trigger_hint = f" (thinking about: {triggers[0]})" if triggers else ""
        return f"Can you go a level deeper on that{trigger_hint}?"
    if action == "verify":
        if ref:
            return f"Can you walk me through the exact implementation — specifically {ref}?"
        return "Can you walk me through the exact implementation you used, step by step?"
    if action == "recovery":
        if reason and "silence" in reason.lower():
            return "No worries — take your time. Could you repeat or rephrase your answer?"
        return f"Let's bring it back to the question: {current.get('text', 'could you address the original question?')}"
    return "Could you elaborate further?"
