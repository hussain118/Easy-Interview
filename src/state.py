"""Typed interview state for the LangGraph controller."""
from __future__ import annotations

from typing import Any, Literal, TypedDict

QuestionSource = Literal["jd", "resume", "github", "scenario"]
Difficulty = Literal["easy", "medium", "hard"]
AnswerQuality = Literal["strong", "good", "shallow", "bluff", "off_topic", "unclear"]
NextAction = Literal[
    "follow_up", "increase_difficulty", "verify", "recovery", "advance", "wrap_up"
]
PlanApprovalStatus = Literal["pending", "approved", "rejected"]
InterviewStatus = Literal[
    "awaiting_hitl_approval", "rejected", "in_progress", "completed"
]


class TranscriptTurn(TypedDict):
    speaker: Literal["agent", "candidate"]
    text: str
    timestamp_ms: int
    node: str
    interrupted: bool


class Evaluation(TypedDict):
    quality: AnswerQuality
    confidence: float
    reason: str
    recommended_action: NextAction


class InterviewState(TypedDict, total=False):
    interview_id: str

    # Static context loaded once from output/prep/*.json (Phase 1 outputs)
    candidate_name: str
    role_title: str
    jd: dict[str, Any]
    resume: dict[str, Any]
    github_evidence: dict[str, Any]

    # HITL / question plan
    question_plan: dict[str, Any]
    plan_approval_status: PlanApprovalStatus
    plan_edits: list[str]
    question_queue: list[dict[str, Any]]  # remaining plan questions, grouped by node

    # Live progress
    current_phase: str
    current_node: str
    current_question_index: int
    current_question: dict[str, Any] | None
    current_answer: str

    last_evaluation: Evaluation | None
    follow_up_count: dict[str, int]  # keyed by topic node name
    difficulty: Difficulty

    transcript: list[TranscriptTurn]

    start_time_ms: int
    elapsed_ms: int

    guardrail_flags: list[str]
    next_action: NextAction | None

    status: InterviewStatus
    completed: bool

    # Internal turn-taking guards (topic nodes only). Declared as real
    # schema fields — not just ad-hoc dict keys — because LangGraph only
    # persists declared channels across an interrupt()/resume checkpoint
    # boundary; anything else silently doesn't survive replay, which was a
    # real bug caught during testing (see prompts/ITERATION_NOTES.md).
    awaiting_answer_for: str | None
    pending_question_text: str
    asked_this_turn: bool
