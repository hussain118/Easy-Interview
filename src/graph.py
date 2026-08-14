"""LangGraph interview controller.

    START -> hitl_approval -[approve/edit]-> intro -> resume_probe -> jd_fit
    -> github_deepdive -> scenario -> candidate_questions -> wrap_up
    -> scoring -> END

    hitl_approval -[reject]-> END

    Each topic is two nodes: <topic> (prepare — decide/ask) and
    <topic>_wait (interrupt for the candidate's answer). <topic> either
    prepares a question (-> edge to <topic>_wait -> evaluate_answer), or
    has nothing left to ask (-> edge straight to the next topic).

    evaluate_answer -[shallow/off_topic/unclear, under follow-up cap]-> back
                     to the same topic node (follow_up/recovery probe)
                    -[bluff, under cap]-> same topic node (verify probe)
                    -[strong/good, or cap reached]-> same topic node, which
                     asks its next queued question or — once its queue is
                     empty — passes through to the next topic itself
                    -[time budget exceeded]-> wrap_up
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from src.nodes._helpers import TOPIC_SEQUENCE, next_topic_after
from src.nodes._topic_node import route_after_prepare
from src.nodes.candidate_questions import candidate_questions
from src.nodes.evaluate_answer import evaluate_answer_node, route_after_evaluation
from src.nodes.github_deepdive import github_deepdive, github_deepdive_wait
from src.nodes.hitl_approval import hitl_approval, route_after_hitl
from src.nodes.intro import intro
from src.nodes.jd_fit import jd_fit, jd_fit_wait
from src.nodes.resume_probe import resume_probe, resume_probe_wait
from src.nodes.scenario import scenario, scenario_wait
from src.nodes.scoring import scoring
from src.nodes.wrap_up import wrap_up
from src.state import InterviewState

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "checkpoints.sqlite"

TOPIC_NODES = {
    "resume_probe": resume_probe,
    "jd_fit": jd_fit,
    "github_deepdive": github_deepdive,
    "scenario": scenario,
}
TOPIC_WAIT_NODES = {
    "resume_probe": resume_probe_wait,
    "jd_fit": jd_fit_wait,
    "github_deepdive": github_deepdive_wait,
    "scenario": scenario_wait,
}


def get_sqlite_checkpointer(db_path: Path | str = DEFAULT_DB_PATH) -> SqliteSaver:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    return SqliteSaver(conn)


def build_graph(checkpointer=None):
    graph = StateGraph(InterviewState)

    graph.add_node("hitl_approval", hitl_approval)
    graph.add_node("intro", intro)
    for name, fn in TOPIC_NODES.items():
        graph.add_node(name, fn)
    for name, fn in TOPIC_WAIT_NODES.items():
        graph.add_node(f"{name}_wait", fn)
    graph.add_node("evaluate_answer", evaluate_answer_node)
    graph.add_node("candidate_questions", candidate_questions)
    graph.add_node("wrap_up", wrap_up)
    graph.add_node("scoring", scoring)

    graph.add_edge(START, "hitl_approval")
    graph.add_conditional_edges(
        "hitl_approval", route_after_hitl, {"intro": "intro", "__end__": END}
    )
    graph.add_edge("intro", "resume_probe")

    for topic in TOPIC_SEQUENCE:
        wait_name = f"{topic}_wait"
        graph.add_conditional_edges(
            topic,
            route_after_prepare,
            {"wait": wait_name, next_topic_after(topic): next_topic_after(topic)},
        )
        graph.add_edge(wait_name, "evaluate_answer")

    # evaluate_answer always loops back to the topic it just evaluated
    # (which self-advances once its question queue is empty — see
    # route_after_prepare) except when the time budget is exceeded.
    eval_destinations = {t: t for t in TOPIC_SEQUENCE}
    eval_destinations["wrap_up"] = "wrap_up"
    graph.add_conditional_edges("evaluate_answer", route_after_evaluation, eval_destinations)

    graph.add_edge("candidate_questions", "wrap_up")
    graph.add_edge("wrap_up", "scoring")
    graph.add_edge("scoring", END)

    return graph.compile(checkpointer=checkpointer)


def build_initial_state(
    *,
    interview_id: str,
    candidate_name: str,
    role_title: str,
    jd: dict,
    resume: dict,
    github_evidence: dict,
    question_plan: dict,
) -> InterviewState:
    return InterviewState(
        interview_id=interview_id,
        candidate_name=candidate_name,
        role_title=role_title,
        jd=jd,
        resume=resume,
        github_evidence=github_evidence,
        question_plan=question_plan,
        plan_approval_status="pending",
        plan_edits=[],
        question_queue=[],
        current_phase="hitl_approval",
        current_node="hitl_approval",
        current_question_index=0,
        current_question=None,
        current_answer="",
        last_evaluation=None,
        follow_up_count={},
        difficulty="medium",
        transcript=[],
        start_time_ms=0,
        elapsed_ms=0,
        guardrail_flags=[],
        next_action=None,
        status="awaiting_hitl_approval",
        completed=False,
        awaiting_answer_for=None,
        pending_question_text="",
        asked_this_turn=False,
    )
