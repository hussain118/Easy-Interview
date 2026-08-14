"""Final scoring entrypoint: loads a completed interview's LangGraph
checkpoint + PREP context, calls the GPT final scorer, applies the
evidence guardrail, and writes output/scorecard.json (exact PDF schema).

    python run_scoring.py --interview-id demo-001
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.agents.scorer import score_interview
from src.graph import build_graph, get_sqlite_checkpointer

ROOT = Path(__file__).resolve().parent
PREP_DIR = ROOT / "output" / "prep"
SCORECARD_PATH = ROOT / "output" / "scorecard.json"
TRANSCRIPT_PATH = ROOT / "output" / "transcript.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Score a completed interview")
    parser.add_argument("--interview-id", required=True)
    args = parser.parse_args()

    checkpointer = get_sqlite_checkpointer()
    graph = build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": args.interview_id}}
    snapshot = graph.get_state(config)
    if not snapshot.values:
        print(f"No interview state found for interview_id={args.interview_id}")
        return 1

    state = snapshot.values
    transcript = state.get("transcript", [])
    if not transcript:
        print("Interview has no transcript yet — nothing to score.")
        return 1

    # Use THIS interview's own embedded context, not whatever currently
    # happens to be in output/prep/*.json — those files may have since
    # been regenerated for a different candidate/JD.
    jd = state.get("jd") or json.loads((PREP_DIR / "jd.json").read_text(encoding="utf-8"))
    resume = state.get("resume") or json.loads((PREP_DIR / "resume.json").read_text(encoding="utf-8"))
    github = state.get("github_evidence") or json.loads((PREP_DIR / "github.json").read_text(encoding="utf-8"))
    question_plan = state.get("question_plan") or json.loads((PREP_DIR / "question_plan.json").read_text(encoding="utf-8"))

    competencies = [c["name"] for c in jd.get("competencies", [])] or ["overall"]

    scorecard = score_interview(
        candidate_name=state.get("candidate_name") or resume.get("candidate_name", ""),
        role=state.get("role_title") or jd.get("role_title", ""),
        interview_date=__import__("datetime").date.today().isoformat(),
        duration_seconds=int((state.get("elapsed_ms") or 0) / 1000),
        competencies=competencies,
        transcript=transcript,
        evaluation_history=state.get("evaluation_history", []),
        resume=resume,
        github_evidence=github,
        question_plan=question_plan,
        guardrail_flags=state.get("guardrail_flags", []),
    )

    SCORECARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCORECARD_PATH.write_text(json.dumps(scorecard, indent=2), encoding="utf-8")
    TRANSCRIPT_PATH.write_text(json.dumps({"turns": transcript}, indent=2), encoding="utf-8")

    print(f"Wrote {SCORECARD_PATH}")
    print(f"Recommendation: {scorecard['recommendation']} (overall_score={scorecard['overall_score']})")
    if any("evidence_guardrail_rejected" in f for f in scorecard["guardrail_flags"]):
        rejected = [f for f in scorecard["guardrail_flags"] if "evidence_guardrail_rejected" in f]
        print(f"Evidence guardrail rejected {len(rejected)} competency score(s): {rejected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
