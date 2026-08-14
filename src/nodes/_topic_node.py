"""Factories for the question-asking topic nodes (resume_probe, jd_fit,
github_deepdive, scenario). Each topic is actually TWO graph nodes:

    <topic>          (prepare) — decides what to ask (pop next queued
                       question, or generate a follow-up/verify/recovery
                       probe), appends the agent's transcript line, and
                       returns normally.
    <topic>_wait      — does nothing but call interrupt() and, on resume,
                       record the candidate's answer.

Why split it this way: LangGraph re-runs an interrupted node's function on
resume, and empirically (verified while testing this graph) a resume value
can end up matched to whichever interrupt() call is hit next rather than
the one that was actually pending, if the SAME node both mutates state and
calls interrupt() across repeated visits (a cycle like ours, where a topic
node is re-entered many times for one interview). Splitting "decide what
to ask" (a real, cleanly-committing node) from "wait for the answer" (a
node with NOTHING before its interrupt() call) sidesteps that entirely:
the wait node has no side effects to redo, so however it's replayed, the
outcome is the same. See prompts/ITERATION_NOTES.md.
"""
from __future__ import annotations

from langgraph.types import interrupt

from src.nodes._helpers import (
    append_transcript_once,
    generate_probe_question,
    guarded_question_text,
    next_topic_after,
    pop_next_for_topic,
)
from src.state import InterviewState

PROBE_ACTIONS = ("follow_up", "verify", "recovery")


def make_prepare_node(topic: str):
    def node_fn(state: InterviewState) -> InterviewState:
        state["current_phase"] = topic
        state["current_node"] = topic

        next_action = state.get("next_action")
        if next_action in PROBE_ACTIONS:
            question_text = generate_probe_question(state, next_action)
            meta = state.get("current_question") or {
                "id": None,
                "competency": None,
                "source_reference": "",
                "difficulty": state.get("difficulty", "medium"),
                "follow_up_triggers": [],
            }
        else:
            popped = pop_next_for_topic(state, topic)
            if popped is None:
                state["asked_this_turn"] = False
                return state
            question_text = popped["text"]
            meta = popped

        question_text = guarded_question_text(state, question_text)
        append_transcript_once(state, "agent", question_text, topic)
        state["current_question"] = meta
        state["next_action"] = None
        state["pending_question_text"] = question_text
        state["asked_this_turn"] = True
        return state

    node_fn.__name__ = topic
    return node_fn


def make_wait_node(topic: str):
    def node_fn(state: InterviewState) -> InterviewState:
        question_text = state.get("pending_question_text", "")
        answer = interrupt({"type": "await_candidate_answer", "node": topic, "question": question_text})
        answer = answer or ""
        append_transcript_once(state, "candidate", answer, topic)
        state["current_answer"] = answer
        return state

    node_fn.__name__ = f"{topic}_wait"
    return node_fn


def route_after_prepare(state: InterviewState) -> str:
    if state.get("asked_this_turn"):
        return "wait"
    return next_topic_after(state["current_phase"])
