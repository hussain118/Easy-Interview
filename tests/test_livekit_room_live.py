"""Live tests against the real LiveKit Cloud project. No audio/video
needed — just REST/gRPC room-service calls, so these are cheap and safe
to run. Skipped by default: RUN_LIVE_TESTS=1 pytest tests/test_livekit_room_live.py
"""
from __future__ import annotations

import asyncio

import pytest
from livekit import api

from src.config import require_key
from src.realtime.livekit_room import (
    build_room_name,
    ensure_room_exists,
    list_active_rooms,
    mint_candidate_token,
    mint_recruiter_observer_token,
)


@pytest.mark.live
def test_mint_candidate_token_is_a_jwt():
    token = mint_candidate_token("pytest-token-check", "Test Candidate")
    assert isinstance(token, str)
    assert token.count(".") == 2  # header.payload.signature


@pytest.mark.live
def test_mint_recruiter_observer_token_is_a_jwt():
    token = mint_recruiter_observer_token("pytest-token-check")
    assert token.count(".") == 2


@pytest.mark.live
def test_create_and_delete_room_roundtrip():
    interview_id = "pytest-room-roundtrip"
    room_name = build_room_name(interview_id)

    asyncio.run(ensure_room_exists(interview_id))

    async def _cleanup():
        url = require_key("LIVEKIT_URL")
        key = require_key("LIVEKIT_API_KEY")
        secret = require_key("LIVEKIT_API_SECRET")
        async with api.LiveKitAPI(url, key, secret) as lk:
            await lk.room.delete_room(api.DeleteRoomRequest(room=room_name))

    asyncio.run(_cleanup())
