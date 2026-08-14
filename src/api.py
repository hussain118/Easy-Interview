"""Minimal backend for the live interview phase: consent recording and
LiveKit token minting. No secrets are ever returned to the frontend —
only the short-lived signed LiveKit JWT (see src/realtime/livekit_room.py).

Run: uvicorn src.api:app --reload --port 8000
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.realtime.livekit_room import (
    build_room_name,
    ensure_room_exists,
    mint_candidate_token,
    mint_recruiter_observer_token,
)

ROOT = Path(__file__).resolve().parent.parent
PREP_DIR = ROOT / "output" / "prep"
CONSENT_DIR = ROOT / "output" / "consent"

CONSENT_STATEMENT = (
    "I consent to this interview being recorded (audio and video) and to "
    "that recording being submitted for grading/evaluation purposes. I "
    "understand I am speaking with an AI interviewer, not a human."
)

app = FastAPI(title="FirstRound Interview API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local/dev only — tighten before any real deployment
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConsentRequest(BaseModel):
    candidate_name: str
    agree: bool


def _load_question_plan() -> dict:
    path = PREP_DIR / "question_plan.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="No question_plan.json found. Run the PREP pipeline first.")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/interviews/{interview_id}/status")
def interview_status(interview_id: str) -> dict:
    plan = _load_question_plan()
    consent_path = CONSENT_DIR / f"{interview_id}.json"
    return {
        "interview_id": interview_id,
        "room_name": build_room_name(interview_id),
        "plan_approved": bool(plan.get("approved_by_human")),
        "consent_recorded": consent_path.exists(),
        "consent_statement": CONSENT_STATEMENT,
    }


@app.get("/interviews/{interview_id}/consent-statement")
def get_consent_statement() -> dict:
    return {"statement": CONSENT_STATEMENT}


@app.post("/interviews/{interview_id}/consent")
def record_consent(interview_id: str, body: ConsentRequest) -> dict:
    if not body.agree:
        raise HTTPException(status_code=400, detail="Consent was not given; cannot proceed to the interview.")
    CONSENT_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "interview_id": interview_id,
        "candidate_name": body.candidate_name,
        "consented_at_ms": int(time.time() * 1000),
        "consent_statement": CONSENT_STATEMENT,
        "agreed": True,
    }
    (CONSENT_DIR / f"{interview_id}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return {"ok": True}


@app.get("/interviews/{interview_id}/token")
async def get_candidate_token(interview_id: str, candidate_name: str = "Candidate") -> dict:
    plan = _load_question_plan()
    if not plan.get("approved_by_human"):
        raise HTTPException(
            status_code=403,
            detail="Question plan is not yet approved by a recruiter. Interview cannot start.",
        )
    consent_path = CONSENT_DIR / f"{interview_id}.json"
    if not consent_path.exists():
        raise HTTPException(status_code=403, detail="Consent has not been recorded for this interview.")

    await ensure_room_exists(interview_id)
    token = mint_candidate_token(interview_id, candidate_name)
    return {
        "token": token,
        "room_name": build_room_name(interview_id),
        # LIVEKIT_URL is not a secret (it's the ws:// endpoint clients connect
        # to), so returning it here is fine — only the API_SECRET stays server-side.
        "livekit_url": _livekit_url(),
    }


@app.get("/interviews/{interview_id}/recruiter-token")
def get_recruiter_token(interview_id: str) -> dict:
    """Bonus: recruiter live-join — silent monitor token (cannot publish audio)."""
    token = mint_recruiter_observer_token(interview_id)
    return {"token": token, "room_name": build_room_name(interview_id), "livekit_url": _livekit_url()}


def _livekit_url() -> str:
    from src.config import require_key

    return require_key("LIVEKIT_URL")
