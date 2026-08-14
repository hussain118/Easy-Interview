"""Fast (no network) checks that the LiveKit Agents worker module and its
Gemini Live model construction are wired correctly. Does NOT exercise a
real audio session — that requires a running LiveKit room + browser/mic,
which this test suite cannot provide. See the live tests
(test_livekit_room_live.py, test_gemini_live_connectivity_live.py,
test_gemini_live_graph_integration_live.py) for what IS verified live.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

WORKER_PATH = Path(__file__).resolve().parent.parent / "livekit_agent" / "interview_worker.py"


def _load_worker_module():
    spec = importlib.util.spec_from_file_location("interview_worker", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_worker_module_imports_and_has_entrypoint():
    module = _load_worker_module()
    assert callable(module.entrypoint)


def test_realtime_model_and_agent_construct_without_network():
    # AgentSession.__init__ calls asyncio.get_event_loop(), which raises if
    # no loop exists in this thread and none was ever set (can happen
    # depending on what other async tests ran earlier in the same pytest
    # session) — construct inside asyncio.run() so a loop is always
    # current, matching how it's actually constructed in the real worker
    # (inside an async entrypoint).
    import asyncio

    async def _construct():
        from livekit.agents import Agent, AgentSession
        from livekit.plugins.google.realtime import RealtimeModel

        from src.config import require_key
        from src.realtime.gemini_live_adapter import DEFAULT_VOICE, LIVE_MODEL_NAME

        model = RealtimeModel(
            instructions="test", model=LIVE_MODEL_NAME, api_key=require_key("GOOGLE_API_KEY"), voice=DEFAULT_VOICE
        )
        agent = Agent(instructions="test", llm=model)
        session = AgentSession()
        assert agent is not None
        assert session is not None

    asyncio.run(_construct())
