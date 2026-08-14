"""Verifies the exact required output paths exist and that
question_plan.json matches the fixed schema from the assignment spec §6.

These tests read already-generated output/prep/*.json files (produced by
`python run_prep.py`) rather than calling the LLM themselves, so they run
fast and free. If the files don't exist yet, they are skipped with a clear
message rather than failing noisily.
"""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PREP_DIR = ROOT / "output" / "prep"

REQUIRED_PATHS = [
    PREP_DIR / "jd.json",
    PREP_DIR / "resume.json",
    PREP_DIR / "github.json",
    PREP_DIR / "question_plan.json",
]


def _skip_if_missing(path: Path):
    if not path.exists():
        pytest.skip(f"{path} not generated yet — run `python run_prep.py` first")


@pytest.mark.parametrize("path", REQUIRED_PATHS)
def test_required_output_path_exists(path):
    _skip_if_missing(path)
    assert path.exists()


def test_question_plan_matches_fixed_schema():
    path = PREP_DIR / "question_plan.json"
    _skip_if_missing(path)
    plan = json.loads(path.read_text(encoding="utf-8"))

    assert set(plan.keys()) >= {"questions", "approved_by_human", "edits_made"}
    assert isinstance(plan["approved_by_human"], bool)
    assert isinstance(plan["edits_made"], list)
    assert isinstance(plan["questions"], list)

    required_q_fields = {
        "id", "text", "competency", "source", "source_reference",
        "difficulty", "follow_up_triggers",
    }
    for q in plan["questions"]:
        assert required_q_fields <= set(q.keys())
        assert q["source"] in {"jd", "resume", "github", "scenario"}
        assert q["difficulty"] in {"easy", "medium", "hard"}
        assert isinstance(q["follow_up_triggers"], list)


def test_question_plan_has_at_least_3_github_grounded_questions():
    path = PREP_DIR / "question_plan.json"
    github_path = PREP_DIR / "github.json"
    _skip_if_missing(path)
    _skip_if_missing(github_path)

    plan = json.loads(path.read_text(encoding="utf-8"))
    github = json.loads(github_path.read_text(encoding="utf-8"))

    github_questions = [q for q in plan["questions"] if q["source"] == "github"]
    if github.get("profile_found") and github.get("repositories_analyzed"):
        assert len(github_questions) >= 3


def test_question_plan_has_twelve_questions():
    path = PREP_DIR / "question_plan.json"
    _skip_if_missing(path)
    plan = json.loads(path.read_text(encoding="utf-8"))
    assert len(plan["questions"]) == 12
