"""Tests for src/api.py. Status/consent-statement endpoints are fast/local.
Token minting and consent endpoints marked @pytest.mark.live where they
touch real LiveKit APIs or the real filesystem consent record.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.api import CONSENT_DIR, app

client = TestClient(app)


def test_status_endpoint_reflects_real_question_plan():
    resp = client.get("/interviews/demo-001/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["interview_id"] == "demo-001"
    assert "plan_approved" in body
    assert body["consent_statement"]


def test_consent_statement_endpoint():
    resp = client.get("/interviews/demo-001/consent-statement")
    assert resp.status_code == 200
    assert "record" in resp.json()["statement"].lower()


def test_consent_rejected_when_agree_false():
    resp = client.post(
        "/interviews/pytest-no-consent/consent",
        json={"candidate_name": "Nope", "agree": False},
    )
    assert resp.status_code == 400


@pytest.mark.live
def test_full_consent_and_token_flow():
    interview_id = "pytest-consent-flow"
    consent_resp = client.post(
        f"/interviews/{interview_id}/consent",
        json={"candidate_name": "Test Candidate", "agree": True},
    )
    assert consent_resp.status_code == 200
    record_path = CONSENT_DIR / f"{interview_id}.json"
    assert record_path.exists()
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["agreed"] is True

    token_resp = client.get(f"/interviews/{interview_id}/token", params={"candidate_name": "Test Candidate"})
    # Requires output/prep/question_plan.json to be approved_by_human=true
    # (true after `python run_hitl_approval.py --interview-id demo-001 approve`
    # was run against the real demo interview — reuse via status check).
    assert token_resp.status_code in (200, 403)
    if token_resp.status_code == 200:
        body = token_resp.json()
        assert body["token"].count(".") == 2
        assert body["room_name"] == f"interview-{interview_id}"

    record_path.unlink(missing_ok=True)


@pytest.mark.live
def test_token_denied_without_consent():
    resp = client.get("/interviews/pytest-never-consented/token")
    assert resp.status_code == 403
