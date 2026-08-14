"""Live smoke test for raw Gemini Live connectivity (no LiveKit, no
microphone needed — validates auth + the audio round trip using
synthetic text input). Skipped by default: RUN_LIVE_TESTS=1 pytest
tests/test_gemini_live_connectivity_live.py -v -s

Confirms: the websocket handshake succeeds, the model produces real
synthesized audio for a text prompt, output transcription works, and
session_resumption handles are actually issued by the API (needed for
the reconnect-on-GoAway strategy — see ARCHITECTURE.md).
"""
from __future__ import annotations

import pytest

from src.realtime.gemini_live_adapter import LIVE_MODEL_NAME
from src.config import require_key


@pytest.mark.live
def test_gemini_live_audio_round_trip():
    import asyncio

    from google import genai
    from google.genai import types

    async def run():
        client = genai.Client(api_key=require_key("GOOGLE_API_KEY"))
        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=types.Content(parts=[types.Part(text="You are a test assistant.")]),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )
        async with client.aio.live.connect(model=LIVE_MODEL_NAME, config=config) as session:
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text="Say the word OK and nothing else.")])
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

    audio_bytes, transcript = asyncio.run(run())
    assert audio_bytes > 0
    assert "ok" in transcript.lower()


@pytest.mark.live
def test_gemini_live_session_resumption_handle_issued():
    import asyncio

    from google import genai
    from google.genai import types

    async def run():
        client = genai.Client(api_key=require_key("GOOGLE_API_KEY"))
        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=types.Content(parts=[types.Part(text="You are a test assistant.")]),
            session_resumption=types.SessionResumptionConfig(),
        )
        handle = None
        async with client.aio.live.connect(model=LIVE_MODEL_NAME, config=config) as session:
            for turn_text in ["Say ONE.", "Say TWO."]:
                await session.send_client_content(
                    turns=types.Content(role="user", parts=[types.Part(text=turn_text)])
                )
                async for msg in session.receive():
                    if msg.session_resumption_update and msg.session_resumption_update.new_handle:
                        handle = msg.session_resumption_update.new_handle
                    if msg.server_content and msg.server_content.turn_complete:
                        break
        return handle

    handle = asyncio.run(run())
    assert handle  # a real resumable-session handle was issued by the API
