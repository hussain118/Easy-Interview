"""Real integration test: LangGraph selects the question, Gemini Live
actually speaks it (real audio synthesized + transcribed back to confirm
it said the right thing), and the real GPT evaluator grades a scripted
candidate answer, which routes the graph to the next turn. This proves
the three authoritative pieces (LangGraph decides, Gemini Live speaks,
GPT evaluates) genuinely work together end to end.

Honest limitation: the "candidate" side is a scripted answer, not a real
microphone — this environment has no audio input hardware. What IS real:
Gemini Live's audio synthesis, the transcription round-trip, the GPT
evaluator call, and the LangGraph routing decision that follows from it.

Skipped by default (costs quota/time): RUN_LIVE_TESTS=1 pytest
tests/test_gemini_live_graph_integration_live.py -v -s
"""
from __future__ import annotations

import asyncio

import pytest
from google import genai
from google.genai import types
from langgraph.types import Command

from src.config import require_key
from src.graph import build_graph, build_initial_state, get_sqlite_checkpointer
from src.providers.openai_client import load_prompt
from src.realtime.gemini_live_adapter import LIVE_MODEL_NAME, build_live_connect_config


async def _speak_and_confirm(session, text: str) -> tuple[int, str]:
    """Asks Gemini Live to say `text` verbatim; returns (audio_bytes, transcript)."""
    await session.send_client_content(
        turns=types.Content(
            role="user",
            parts=[types.Part(text=f'Say exactly, word for word: "{text}"')],
        )
    )
    audio_bytes = 0
    transcript = ""
    async for msg in session.receive():
        if msg.data:
            audio_bytes += len(msg.data)
        if msg.server_content and msg.server_content.output_transcription:
            transcript += msg.server_content.output_transcription.text or ""
        if msg.server_content and msg.server_content.turn_complete:
            break
    return audio_bytes, transcript


@pytest.mark.live
def test_graph_plus_gemini_speech_plus_gpt_evaluation(tmp_path):
    checkpointer = get_sqlite_checkpointer(tmp_path / "cp.sqlite")
    graph = build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "live-integration"}}

    def q(id_, source, comp, text):
        return {
            "id": id_, "text": text, "competency": comp, "source": source,
            "source_reference": "", "difficulty": "medium", "follow_up_triggers": [],
        }

    plan = {
        "questions": [
            q("q1", "resume", "backend", "Tell me about a project you built."),
            q("q2", "jd", "git", "How do you use Git in a team setting?"),
        ],
        "approved_by_human": False,
        "edits_made": [],
    }
    state = build_initial_state(
        interview_id="live-integration", candidate_name="Test Candidate",
        role_title="Junior AI Engineer", jd={}, resume={}, github_evidence={},
        question_plan=plan,
    )

    result = graph.invoke(state, config=config)  # pauses at HITL
    result = graph.invoke(Command(resume={"action": "approve"}), config=config)  # pauses asking q1
    question_text = result["__interrupt__"][0].value["question"]
    assert question_text == "Tell me about a project you built."

    async def speak_it():
        client = genai.Client(api_key=require_key("GOOGLE_API_KEY"))
        instructions = load_prompt("live_interviewer.md")
        live_config = build_live_connect_config(instructions)
        async with client.aio.live.connect(model=LIVE_MODEL_NAME, config=live_config) as session:
            return await _speak_and_confirm(session, question_text)

    audio_bytes, transcript = asyncio.run(speak_it())
    assert audio_bytes > 0
    assert "project" in transcript.lower()

    # Real GPT evaluation of a scripted (not mic-captured) candidate answer
    scripted_answer = (
        "I built a REST API for internal tooling using FastAPI, with pytest "
        "for testing and a small Postgres schema for storage."
    )
    result = graph.invoke(Command(resume=scripted_answer), config=config)
    # Either probing this topic again or having moved on — either way, a
    # real GPT evaluation must have happened (last_evaluation populated).
    saved = graph.get_state(config).values
    assert saved["last_evaluation"] is not None
    assert saved["last_evaluation"]["quality"] in {
        "strong", "good", "shallow", "bluff", "off_topic", "unclear",
    }
