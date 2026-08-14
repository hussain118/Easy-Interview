"""Server-side LiveKit room + access-token management.

Backend-only: LIVEKIT_API_SECRET never leaves this module (never sent to
the frontend — only the short-lived signed JWT token is). Uses the real
LiveKit Cloud project from .env; room creation and token minting are
plain authenticated API calls, no audio/video required to exercise them.
"""
from __future__ import annotations

from livekit import api

from src.config import require_key

TOKEN_TTL_SECONDS = 60 * 60  # 1 hour — long enough for one interview session


def _credentials() -> tuple[str, str, str]:
    url = require_key("LIVEKIT_URL")
    key = require_key("LIVEKIT_API_KEY")
    secret = require_key("LIVEKIT_API_SECRET")
    return url, key, secret


def build_room_name(interview_id: str) -> str:
    return f"interview-{interview_id}"


def mint_candidate_token(interview_id: str, candidate_name: str) -> str:
    """Short-lived join token for the candidate's browser. Only this JWT
    (not the API secret) is ever sent to the frontend.
    """
    _, api_key, api_secret = _credentials()
    room = build_room_name(interview_id)
    grants = api.VideoGrants(
        room_join=True,
        room=room,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
    )
    token = (
        api.AccessToken(api_key, api_secret)
        .with_identity(f"candidate-{interview_id}")
        .with_name(candidate_name or "Candidate")
        .with_grants(grants)
        .with_ttl(__import__("datetime").timedelta(seconds=TOKEN_TTL_SECONDS))
    )
    return token.to_jwt()


def mint_recruiter_observer_token(interview_id: str) -> str:
    """Silent-monitor token (bonus: recruiter live-join) — can subscribe,
    cannot publish audio/video, so it never talks over the interview.
    """
    _, api_key, api_secret = _credentials()
    room = build_room_name(interview_id)
    grants = api.VideoGrants(
        room_join=True,
        room=room,
        can_publish=False,
        can_subscribe=True,
        can_publish_data=True,  # can still inject a text question (bonus)
        hidden=True,
    )
    token = (
        api.AccessToken(api_key, api_secret)
        .with_identity(f"recruiter-{interview_id}")
        .with_name("Recruiter (observer)")
        .with_grants(grants)
        .with_ttl(__import__("datetime").timedelta(seconds=TOKEN_TTL_SECONDS))
    )
    return token.to_jwt()


async def ensure_room_exists(interview_id: str) -> None:
    """Explicitly creates the room ahead of time (idempotent — LiveKit
    also auto-creates a room on first join, but doing this lets us fail
    fast with a clear error if credentials are bad).
    """
    url, api_key, api_secret = _credentials()
    async with api.LiveKitAPI(url, api_key, api_secret) as lk:
        await lk.room.create_room(api.CreateRoomRequest(name=build_room_name(interview_id)))


async def list_active_rooms() -> list[str]:
    url, api_key, api_secret = _credentials()
    async with api.LiveKitAPI(url, api_key, api_secret) as lk:
        resp = await lk.room.list_rooms(api.ListRoomsRequest())
        return [r.name for r in resp.rooms]
