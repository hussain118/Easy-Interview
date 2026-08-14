"""Reference driver loop tying the compiled graph to a RealtimeInterviewAdapter
via LangGraph's interrupt()/Command(resume=...) mechanism. This is what
Prompt 3's real Gemini Live/LiveKit adapter will be driven by — the graph
itself has zero knowledge of the adapter.
"""
from __future__ import annotations

from typing import Any, Callable

from langgraph.types import Command

from src.realtime.adapter import RealtimeInterviewAdapter

ResumeFn = Callable[[dict[str, Any]], Any]


def run_until_interrupt_or_end(graph, config: dict, initial_state=None) -> dict:
    """Invoke the graph until it hits an interrupt() or reaches END."""
    if initial_state is not None:
        return graph.invoke(initial_state, config=config)
    return graph.invoke(None, config=config)


def resume(graph, config: dict, resume_value: Any) -> dict:
    return graph.invoke(Command(resume=resume_value), config=config)


def make_adapter_resume_fn(adapter: RealtimeInterviewAdapter, hitl_decision: dict) -> ResumeFn:
    """Builds a resume-value function: HITL interrupts get the recruiter's
    pre-supplied decision; candidate-turn interrupts get spoken via the
    adapter and answered via the adapter's transcription.
    """

    def resume_fn(payload: dict[str, Any]) -> Any:
        if payload.get("type") == "hitl_question_plan_approval":
            return hitl_decision
        adapter.speak(payload["question"])
        return adapter.receive_candidate_turn()

    return resume_fn


def run_full_session(graph, config: dict, initial_state, resume_fn: ResumeFn) -> dict:
    """Drives the graph from initial_state to completion, calling resume_fn
    for every interrupt encountered along the way (HITL, then each
    candidate turn).
    """
    result = run_until_interrupt_or_end(graph, config, initial_state)
    while isinstance(result, dict) and result.get("__interrupt__"):
        payload = result["__interrupt__"][0].value
        result = resume(graph, config, resume_fn(payload))
    return result
