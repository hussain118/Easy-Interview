"""Tests run_hitl_approval.py's approve/edit/reject paths against an
isolated prep dir + SQLite checkpoint (never touches the real
output/prep/question_plan.json). No network calls.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

WORKER_PATH = Path(__file__).resolve().parent.parent / "run_hitl_approval.py"


def _load_cli_module():
    spec = importlib.util.spec_from_file_location("run_hitl_approval", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_prep_files(prep_dir: Path):
    prep_dir.mkdir(parents=True, exist_ok=True)
    (prep_dir / "jd.json").write_text(json.dumps({"role_title": "Junior AI Engineer"}), encoding="utf-8")
    (prep_dir / "resume.json").write_text(json.dumps({"candidate_name": "Test Candidate"}), encoding="utf-8")
    (prep_dir / "github.json").write_text(json.dumps({"profile_found": False}), encoding="utf-8")
    plan = {
        "questions": [
            {
                "id": "q1", "text": "Tell me about a project.", "competency": "backend",
                "source": "resume", "source_reference": "", "difficulty": "medium",
                "follow_up_triggers": [],
            }
        ],
        "approved_by_human": False,
        "edits_made": [],
    }
    (prep_dir / "question_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    return plan


def _run_cli(module, monkeypatch, prep_dir, argv):
    monkeypatch.setattr(module, "PREP_DIR", prep_dir)
    monkeypatch.setattr(sys, "argv", ["run_hitl_approval.py"] + argv)
    return module.main()


def _patch_checkpointer(module, monkeypatch, tmp_path):
    from src.graph import get_sqlite_checkpointer

    def fake_checkpointer():
        return get_sqlite_checkpointer(tmp_path / "cp.sqlite")

    monkeypatch.setattr(module, "get_sqlite_checkpointer", fake_checkpointer)


def test_approve_updates_plan(tmp_path, monkeypatch):
    module = _load_cli_module()
    prep_dir = tmp_path / "prep"
    _write_prep_files(prep_dir)
    _patch_checkpointer(module, monkeypatch, tmp_path)

    exit_code = _run_cli(module, monkeypatch, prep_dir, ["approve", "--interview-id", "t-approve"])
    assert exit_code == 0
    plan = json.loads((prep_dir / "question_plan.json").read_text(encoding="utf-8"))
    assert plan["approved_by_human"] is True


def test_reject_marks_status_rejected(tmp_path, monkeypatch):
    module = _load_cli_module()
    prep_dir = tmp_path / "prep"
    _write_prep_files(prep_dir)
    _patch_checkpointer(module, monkeypatch, tmp_path)

    exit_code = _run_cli(module, monkeypatch, prep_dir, ["reject", "--interview-id", "t-reject"])
    assert exit_code == 0
    plan = json.loads((prep_dir / "question_plan.json").read_text(encoding="utf-8"))
    assert plan["approved_by_human"] is False


def test_edit_applies_edited_questions(tmp_path, monkeypatch):
    module = _load_cli_module()
    prep_dir = tmp_path / "prep"
    _write_prep_files(prep_dir)
    _patch_checkpointer(module, monkeypatch, tmp_path)

    edited = [
        {
            "id": "q1", "text": "Edited question text?", "competency": "backend",
            "source": "resume", "source_reference": "", "difficulty": "easy",
            "follow_up_triggers": [],
        }
    ]
    edited_path = tmp_path / "edited.json"
    edited_path.write_text(json.dumps(edited), encoding="utf-8")

    exit_code = _run_cli(
        module, monkeypatch, prep_dir,
        ["edit", "--interview-id", "t-edit", "--edited-plan", str(edited_path), "--notes", "trimmed"],
    )
    assert exit_code == 0
    plan = json.loads((prep_dir / "question_plan.json").read_text(encoding="utf-8"))
    assert plan["approved_by_human"] is True
    assert plan["questions"] == edited
    assert "trimmed" in plan["edits_made"]
