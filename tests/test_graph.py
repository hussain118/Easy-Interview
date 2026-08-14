"""LangGraph interview controller tests. GPT is mocked throughout (via
monkeypatch on src.nodes.evaluate_answer.evaluate_answer) — no live calls,
no cost. Covers: compilation, normal progression, adaptive routing
(shallow/strong/bluff/off_topic/silence), follow-up cap, HITL
approve/edit/reject, SQLite checkpoint + dropped-call recovery, invalid
GPT output handling, and deterministic routing.
"""
from __future__ import annotations

from langgraph.types import Command

from src.graph import build_graph, build_initial_state, get_sqlite_checkpointer
from src.agents.evaluator import normalize_evaluation
from src.nodes.evaluate_answer import evaluate_answer_node, route_after_evaluation
from src.realtime.mock_adapter import MockRealtimeAdapter
from src.realtime.session_runner import make_adapter_resume_fn, run_full_session

from tests.graph_fixtures import make_graph_and_config, make_initial_state


def patch_evaluator(monkeypatch, evaluations):
    """Evaluator returns items from `evaluations` in order, then 'good'."""
    queue = list(evaluations)

    def fake(**kwargs):
        if queue:
            return queue.pop(0)
        return {"quality": "good", "confidence": 0.8, "reason": "fine", "recommended_action": "next_question"}

    monkeypatch.setattr("src.nodes.evaluate_answer.evaluate_answer", fake)


def ev(quality, reason="r"):
    return {"quality": quality, "confidence": 0.7, "reason": reason, "recommended_action": "next_question"}


def run(tmp_path, thread_id, answers, evaluations, hitl_decision=None):
    graph, config = make_graph_and_config(tmp_path, thread_id)
    state = make_initial_state(thread_id)
    adapter = MockRealtimeAdapter(scripted_answers=list(answers))
    resume_fn = make_adapter_resume_fn(adapter, hitl_decision or {"action": "approve"})
    result = run_full_session(graph, config, state, resume_fn)
    return result, adapter


def agent_texts(result, node):
    return [t["text"] for t in result["transcript"] if t["node"] == node and t["speaker"] == "agent"]


# 1. graph compilation -------------------------------------------------
def test_graph_compiles(tmp_path):
    graph, _ = make_graph_and_config(tmp_path)
    nodes = set(graph.get_graph().nodes.keys())
    required = {
        "hitl_approval", "intro", "resume_probe", "jd_fit", "github_deepdive",
        "scenario", "evaluate_answer", "candidate_questions", "wrap_up", "scoring",
    }
    assert required <= nodes


# 2. normal progression through all topics ------------------------------
def test_normal_progression_reaches_scoring(tmp_path, monkeypatch):
    patch_evaluator(monkeypatch, [ev("good")] * 7)
    answers = ["a decent answer"] * 7 + ["no questions from me"]
    result, _ = run(tmp_path, "normal", answers, [])
    assert result["status"] == "completed"
    assert result["completed"] is True
    assert len(agent_texts(result, "resume_probe")) == 2  # q1, q2 — no follow-ups
    assert len(agent_texts(result, "scenario")) == 1


# 3. shallow -> follow_up -------------------------------------------------
def test_shallow_triggers_follow_up(tmp_path, monkeypatch):
    patch_evaluator(monkeypatch, [ev("shallow"), ev("good")])
    answers = ["thin answer", "better answer"] + ["ok"] * 6 + ["none"]
    result, _ = run(tmp_path, "shallow", answers, [])
    texts = agent_texts(result, "resume_probe")
    assert len(texts) == 3  # q1, follow_up, q2
    assert "deeper" in texts[1].lower()


# 4. strong -> increase difficulty ---------------------------------------
def test_strong_increases_difficulty(tmp_path, monkeypatch):
    patch_evaluator(monkeypatch, [ev("strong")])
    answers = ["excellent detailed answer"] + ["ok"] * 6 + ["none"]
    result, _ = run(tmp_path, "strong", answers, [])
    assert result["difficulty"] == "hard"


# 5. bluff -> verify -------------------------------------------------------
def test_bluff_triggers_verify(tmp_path, monkeypatch):
    patch_evaluator(monkeypatch, [ev("bluff"), ev("good")])
    answers = ["confident vague claim", "ok here are specifics"] + ["ok"] * 6 + ["none"]
    result, _ = run(tmp_path, "bluff", answers, [])
    texts = agent_texts(result, "resume_probe")
    assert len(texts) == 3
    assert "walk me through the exact implementation" in texts[1].lower()


# 6. off-topic -> recovery --------------------------------------------------
def test_off_topic_triggers_recovery(tmp_path, monkeypatch):
    patch_evaluator(monkeypatch, [ev("off_topic"), ev("good")])
    answers = ["talking about something else", "ok back on topic"] + ["ok"] * 6 + ["none"]
    result, _ = run(tmp_path, "offtopic", answers, [])
    texts = agent_texts(result, "resume_probe")
    assert len(texts) == 3
    assert "let's bring it back" in texts[1].lower()


# 7. silence -> recovery, no GPT call needed --------------------------------
def test_silence_triggers_recovery_without_gpt_call(tmp_path, monkeypatch):
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return ev("good")

    monkeypatch.setattr("src.nodes.evaluate_answer.evaluate_answer", fake)
    answers = ["", "here is my real answer"] + ["ok"] * 6 + ["none"]
    result, _ = run(tmp_path, "silence", answers, [])
    texts = agent_texts(result, "resume_probe")
    assert len(texts) == 3
    assert "take your time" in texts[1].lower()
    assert len(calls) == 7  # 8 topic answers total, minus the 1 silent turn


# 8. max 2 follow-ups then advance (no infinite loop) -----------------------
def test_max_two_follow_ups_then_advances(tmp_path, monkeypatch):
    patch_evaluator(monkeypatch, [ev("shallow"), ev("shallow"), ev("shallow")])
    answers = ["a1", "a2", "a3", "a4"] + ["ok"] * 6 + ["none"]
    result, _ = run(tmp_path, "maxfollowup", answers, [])
    texts = agent_texts(result, "resume_probe")
    assert len(texts) == 4  # q1 + 2 follow-ups (cap) + q2 — never a 3rd follow-up
    assert result["status"] == "completed"


# 9. HITL approval ------------------------------------------------------
def test_hitl_approval(tmp_path, monkeypatch):
    patch_evaluator(monkeypatch, [])
    answers = ["ok"] * 7 + ["none"]
    result, _ = run(tmp_path, "hitl-approve", answers, [], hitl_decision={"action": "approve"})
    assert result["plan_approval_status"] == "approved"
    assert result["question_plan"]["approved_by_human"] is True
    assert any(t["node"] == "intro" for t in result["transcript"])


# 10. HITL edit -----------------------------------------------------------
def test_hitl_edit_applies_changes(tmp_path, monkeypatch):
    patch_evaluator(monkeypatch, [])
    trimmed = [
        {
            "id": "q1", "text": "Edited question?", "competency": "backend",
            "source": "resume", "source_reference": "", "difficulty": "easy",
            "follow_up_triggers": [],
        }
    ]
    decision = {"action": "edit", "edited_questions": trimmed, "notes": "trimmed to 1 question"}
    answers = ["ok", "none"]
    result, _ = run(tmp_path, "hitl-edit", answers, [], hitl_decision=decision)
    assert result["plan_approval_status"] == "approved"
    assert result["question_plan"]["questions"] == trimmed
    assert "trimmed to 1 question" in result["question_plan"]["edits_made"]
    assert agent_texts(result, "resume_probe") == ["Edited question?"]


# 11. HITL rejection --------------------------------------------------------
def test_hitl_rejection_stops_before_any_interview(tmp_path, monkeypatch):
    patch_evaluator(monkeypatch, [])
    result, _ = run(tmp_path, "hitl-reject", [], [], hitl_decision={"action": "reject"})
    assert result["plan_approval_status"] == "rejected"
    assert result["status"] == "rejected"
    assert result["completed"] is False
    assert result["transcript"] == []  # nothing ran — no intro, no questions


# 12 & 13. SQLite checkpoint + dropped-call recovery -------------------------
def test_sqlite_checkpoint_and_dropped_call_recovery(tmp_path, monkeypatch):
    patch_evaluator(monkeypatch, [])
    db_path = tmp_path / "drop.sqlite"
    thread_id = "drop-thread"
    config = {"configurable": {"thread_id": thread_id}}

    cp1 = get_sqlite_checkpointer(db_path)
    graph1 = build_graph(checkpointer=cp1)
    state = make_initial_state(thread_id)

    result = graph1.invoke(state, config=config)  # pauses at HITL
    result = graph1.invoke(Command(resume={"action": "approve"}), config=config)  # pauses at q1
    assert result["__interrupt__"][0].value["node"] == "resume_probe"

    result = graph1.invoke(Command(resume="answer to q1"), config=config)  # pauses at q2
    assert result["__interrupt__"][0].value["node"] == "resume_probe"
    saved_state = graph1.get_state(config)
    assert saved_state.values["current_phase"] == "resume_probe"
    # paused waiting for q2's answer: q1 AND q2 already popped (q2's prepare
    # step, which pops it, runs and commits before its wait node pauses)
    assert len(saved_state.values["question_queue"]) == 5  # q3..q7 remain

    # --- simulate process restart: fresh graph object, same db file/thread ---
    del graph1
    cp2 = get_sqlite_checkpointer(db_path)
    graph2 = build_graph(checkpointer=cp2)

    recovered_state = graph2.get_state(config)
    assert recovered_state.values["current_phase"] == "resume_probe"
    assert recovered_state.values["transcript"][-1]["node"] == "resume_probe"

    # resume — must continue from q2, NOT restart from hitl_approval/intro
    result = graph2.invoke(Command(resume="answer to q2"), config=config)
    assert result["__interrupt__"][0].value["node"] == "jd_fit"
    intro_turns = [t for t in result["transcript"] if t["node"] == "intro"]
    assert len(intro_turns) == 1  # intro ran exactly once, not re-run on recovery


# 14. invalid GPT evaluation is normalized safely ----------------------------
def test_invalid_gpt_evaluation_is_normalized():
    bad = {"quality": "definitely_strong!!", "confidence": "not-a-number", "recommended_action": "yell"}
    normalized = normalize_evaluation(bad)
    assert normalized["quality"] == "unclear"
    assert normalized["confidence"] == 0.0
    assert normalized["recommended_action"] == "next_question"

    out_of_range = {"quality": "strong", "confidence": 5.0, "reason": "x", "recommended_action": "verify"}
    assert normalize_evaluation(out_of_range)["confidence"] == 1.0


# 15. deterministic routing ignores recommended_action ------------------------
def test_routing_ignores_recommended_action_uses_quality_only(monkeypatch):
    # GPT says quality=good (should advance) but recommended_action=follow_up
    # (conflicting). The node's decision must follow `quality`, not the
    # LLM's free-text suggestion.
    monkeypatch.setattr(
        "src.nodes.evaluate_answer.evaluate_answer",
        lambda **kwargs: {"quality": "good", "confidence": 0.9, "reason": "x", "recommended_action": "follow_up"},
    )
    state = {
        "current_phase": "resume_probe",
        "current_answer": "a real answer",
        "current_question": {"text": "q", "competency": "c", "source_reference": ""},
        "transcript": [],
        "follow_up_count": {},
        "difficulty": "medium",
    }
    state = evaluate_answer_node(state)
    assert state["next_action"] is None  # NOT "follow_up" — quality=good wins
    assert route_after_evaluation(state) == "resume_probe"  # loops back to ask next queued Q
    assert state["next_action"] is None  # advance path clears next_action (no probe pending)


# 16. banned-question guardrail blocks before reaching the candidate ---------
def test_banned_question_blocked_before_reaching_candidate(tmp_path, monkeypatch):
    patch_evaluator(monkeypatch, [])
    from tests.graph_fixtures import make_question_plan
    bad_plan = make_question_plan()
    bad_plan["questions"][0]["text"] = "What is your marital status?"

    graph, config = make_graph_and_config(tmp_path, "banned")
    state = make_initial_state("banned")
    state["question_plan"] = bad_plan
    adapter = MockRealtimeAdapter(scripted_answers=["ok"] * 8)
    resume_fn = make_adapter_resume_fn(adapter, {"action": "approve"})
    result = run_full_session(graph, config, state, resume_fn)

    texts = agent_texts(result, "resume_probe")
    assert "marital status" not in texts[0].lower()
    assert any("banned_question_blocked" in f for f in result["guardrail_flags"])
