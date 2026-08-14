"""LiveKit Agents worker — the real candidate-facing audio interview.

Run (separate long-lived process, per LiveKit Agents' normal deployment
model):

    python livekit_agent/interview_worker.py dev      # local dev mode
    python livekit_agent/interview_worker.py start     # production mode

Responsibility split (per ARCHITECTURE.md):
  - LiveKit / this worker's AgentSession   -> real-time audio transport,
    turn detection, barge-in (built into the framework's turn/VAD logic).
  - Gemini Live (RealtimeModel)            -> speaks/listens; NEVER
    decides answer quality — it only says what LangGraph tells it to say.
  - GPT (src/agents/evaluator.py)          -> the only thing that grades
    an answer (strong/good/shallow/bluff/off_topic/unclear).
  - LangGraph (src/graph.py)               -> the only thing that decides
    what happens next (follow_up/verify/recovery/advance/wrap_up).

This file's job is narrow: bridge AgentSession's async, event-driven audio
turns to the graph's interrupt()/Command(resume=...) checkpointed model.
It never evaluates an answer itself and never chooses the next question.

NOT LIVE-TESTED: this file was written and verified to import/construct
correctly against the installed livekit-agents + livekit-plugins-google
APIs, but exercising it end-to-end requires a running LiveKit room with a
real candidate/browser and microphone, which this environment does not
have. The pieces it's built from (LiveKit room/token minting, Gemini Live
audio synthesis+transcription+session resumption, and the LangGraph
controller itself) are each independently live-verified — see
tests/test_livekit_room_live.py, tests/test_gemini_live_connectivity_live.py,
and tests/test_gemini_live_graph_integration_live.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

# Running this file directly (`python livekit_agent/interview_worker.py`)
# only puts livekit_agent/ on sys.path, not the project root, so the `src`
# package can't be found — add it explicitly (found this the first time
# the worker was actually run, not while writing it).
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from langgraph.types import Command
from livekit import agents
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli
from livekit.plugins.google.realtime import RealtimeModel

from src.config import require_key
from src.graph import build_graph, build_initial_state, get_sqlite_checkpointer
from src.providers.openai_client import load_prompt
from src.realtime.gemini_live_adapter import DEFAULT_VOICE, LIVE_MODEL_NAME

logger = logging.getLogger("interview_worker")

ROOT = Path(__file__).resolve().parent.parent
PREP_DIR = ROOT / "output" / "prep"
TRANSCRIPT_PATH = ROOT / "output" / "transcript.json"
LATENCY_LOG_PATH = ROOT / "output" / "latency_measurements.jsonl"


def _load_prep_context() -> tuple[dict, dict, dict, dict]:
    jd = json.loads((PREP_DIR / "jd.json").read_text(encoding="utf-8"))
    resume = json.loads((PREP_DIR / "resume.json").read_text(encoding="utf-8"))
    github = json.loads((PREP_DIR / "github.json").read_text(encoding="utf-8"))
    plan = json.loads((PREP_DIR / "question_plan.json").read_text(encoding="utf-8"))
    return jd, resume, github, plan


def _record_latency(seconds: float) -> None:
    LATENCY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LATENCY_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp_ms": int(time.time() * 1000), "latency_seconds": round(seconds, 3)}) + "\n")


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    interview_id = ctx.room.name.replace("interview-", "") or ctx.room.name
    logger.info("Interview worker joined room %s (interview_id=%s)", ctx.room.name, interview_id)

    jd, resume, github, plan = _load_prep_context()
    if not plan.get("approved_by_human"):
        raise RuntimeError(
            "output/prep/question_plan.json has approved_by_human=false. "
            "Run the HITL approval step before starting the live call — "
            "the interview must not start without recruiter approval."
        )

    checkpointer = get_sqlite_checkpointer()
    graph = build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": interview_id}}

    existing = await asyncio.to_thread(graph.get_state, config)
    if not existing.values:
        initial = build_initial_state(
            interview_id=interview_id,
            candidate_name=resume.get("candidate_name") or "Candidate",
            role_title=jd.get("role_title") or "this role",
            jd=jd,
            resume=resume,
            github_evidence=github,
            question_plan=plan,
        )
        await asyncio.to_thread(graph.invoke, initial, config)
        # First pause is always the HITL gate; approval already happened
        # offline (approved_by_human=true, checked above), so resume it
        # immediately here rather than making the candidate wait on it.
        await asyncio.to_thread(graph.invoke, Command(resume={"action": "approve"}), config)
    else:
        logger.info(
            "Resuming existing interview state at node %s (dropped-call recovery)",
            existing.values.get("current_phase"),
        )

    system_instruction = load_prompt("live_interviewer.md")
    model = RealtimeModel(
        instructions=system_instruction,
        model=LIVE_MODEL_NAME,
        api_key=require_key("GOOGLE_API_KEY"),
        voice=DEFAULT_VOICE,
    )
    agent = Agent(instructions=system_instruction, llm=model)
    session = AgentSession()

    pending_answer: asyncio.Queue[str] = asyncio.Queue()
    turn_state: dict[str, float] = {}
    barge_in_count = 0

    def _mark_last_agent_turn_interrupted() -> None:
        snapshot = graph.get_state(config)
        transcript = list(snapshot.values.get("transcript", []))
        for turn in reversed(transcript):
            if turn["speaker"] == "agent":
                turn["interrupted"] = True
                break
        graph.update_state(config, {"transcript": transcript})

    @session.on("user_state_changed")
    def _on_user_state_changed(ev):
        nonlocal barge_in_count
        if ev.old_state == "speaking" and ev.new_state != "speaking":
            turn_state["candidate_stopped_at"] = time.time()
        if ev.new_state == "speaking" and session.agent_state == "speaking":
            barge_in_count += 1
            ts = time.time()
            logger.info("BARGE-IN #%d detected at %s (agent was speaking)", barge_in_count, ts)
            asyncio.ensure_future(asyncio.to_thread(_mark_last_agent_turn_interrupted))

    @session.on("agent_state_changed")
    def _on_agent_state_changed(ev):
        if ev.new_state == "speaking" and "candidate_stopped_at" in turn_state:
            latency = time.time() - turn_state.pop("candidate_stopped_at")
            logger.info("Latency (candidate stop -> agent start): %.3fs", latency)
            _record_latency(latency)

    @session.on("conversation_item_added")
    def _on_conversation_item_added(ev):
        item = ev.item
        # item can be a ChatMessage (role="user"/"assistant") or an
        # AgentHandoff (no .role at all) — found by actually running the
        # worker against a real room, not assumed from the type hints.
        if getattr(item, "role", None) != "user":
            return
        text = "".join(str(c) for c in (item.content or []) if isinstance(c, str))
        if text.strip():
            pending_answer.put_nowait(text)

    await session.start(agent=agent, room=ctx.room)

    def speak(text: str) -> None:
        # generate_reply() is sync and returns immediately once the speech
        # is *scheduled* — do not await full playout here. We don't need
        # to block until the AI finishes talking before listening for the
        # candidate's answer; that's handled independently by the
        # conversation_item_added event/turn detection. Awaiting the
        # handle's playout was found (by actually running this against a
        # real room) to hang indefinitely with no subscriber attached —
        # not needed for correctness, only removed a false dependency.
        session.generate_reply(
            instructions=(
                "Say the following to the candidate, in your own natural "
                f'spoken phrasing, preserving all technical specifics: "{text}"'
            )
        )

    # Main driver loop: uniform for both a fresh start and a
    # dropped-call recovery — always ask the graph what it's currently
    # paused on rather than assuming state.
    while True:
        snapshot = await asyncio.to_thread(graph.get_state, config)
        if not snapshot.interrupts:
            break  # reached END (scoring done)
        payload = snapshot.interrupts[0].value
        if payload.get("type") != "await_candidate_answer":
            # Shouldn't happen post-HITL, but fail safe rather than loop.
            logger.warning("Unexpected interrupt type at resume: %s", payload)
            break

        question_text = payload["question"]
        speak(question_text)
        answer = await pending_answer.get()
        await asyncio.to_thread(graph.invoke, Command(resume=answer), config)

    final_state = (await asyncio.to_thread(graph.get_state, config)).values
    TRANSCRIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_PATH.write_text(
        json.dumps({"turns": final_state.get("transcript", [])}, indent=2), encoding="utf-8"
    )
    logger.info("Interview complete. barge_in_count=%d. Transcript written to %s", barge_in_count, TRANSCRIPT_PATH)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
