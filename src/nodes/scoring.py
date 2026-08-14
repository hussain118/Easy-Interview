"""Stub terminal node. Finalizes interview status/timing only.

The real competency scoring pipeline (transcript -> scorecard.json with
evidence quotes) is a later phase — explicitly out of scope here.
"""
from __future__ import annotations

from src.nodes._helpers import now_ms
from src.state import InterviewState

NODE = "scoring"


def scoring(state: InterviewState) -> InterviewState:
    state["current_phase"] = NODE
    state["current_node"] = NODE
    state["status"] = "completed"
    state["completed"] = True
    state["elapsed_ms"] = now_ms() - state.get("start_time_ms", now_ms())
    return state
