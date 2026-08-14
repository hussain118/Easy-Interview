"""Recruiter HITL approval CLI — the offline step from the PDF's Phase 1
workflow diagram ("[ HITL INTERRUPT — recruiter approves ]"), run before
a candidate ever gets an interview link.

This starts the SAME LangGraph checkpoint the live worker will later
resume (same thread_id = interview_id), drives it to the real
hitl_approval interrupt(), and resumes it with the recruiter's decision.
The graph genuinely pauses here — nothing runs before this completes.

    python run_hitl_approval.py --interview-id demo-001 approve
    python run_hitl_approval.py --interview-id demo-001 reject
    python run_hitl_approval.py --interview-id demo-001 edit --edited-plan path/to/edited_questions.json --notes "trimmed to 8 questions"

After approval, output/prep/question_plan.json is rewritten with
approved_by_human=true and edits_made populated, so both the graph
checkpoint AND the on-disk deliverable stay consistent.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from langgraph.types import Command

from src.graph import build_graph, build_initial_state, get_sqlite_checkpointer

ROOT = Path(__file__).resolve().parent
PREP_DIR = ROOT / "output" / "prep"


def main() -> int:
    parser = argparse.ArgumentParser(description="Recruiter HITL approval for a generated question plan")
    parser.add_argument("action", choices=["approve", "edit", "reject"])
    parser.add_argument("--interview-id", required=True)
    parser.add_argument("--edited-plan", type=Path, help="Path to a JSON file: a list of question objects")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    jd = json.loads((PREP_DIR / "jd.json").read_text(encoding="utf-8"))
    resume = json.loads((PREP_DIR / "resume.json").read_text(encoding="utf-8"))
    github = json.loads((PREP_DIR / "github.json").read_text(encoding="utf-8"))
    plan = json.loads((PREP_DIR / "question_plan.json").read_text(encoding="utf-8"))

    checkpointer = get_sqlite_checkpointer()
    graph = build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": args.interview_id}}

    snapshot = graph.get_state(config)
    if not snapshot.values:
        initial = build_initial_state(
            interview_id=args.interview_id,
            candidate_name=resume.get("candidate_name") or "Candidate",
            role_title=jd.get("role_title") or "this role",
            jd=jd,
            resume=resume,
            github_evidence=github,
            question_plan=plan,
        )
        result = graph.invoke(initial, config=config)
    else:
        result = snapshot.values
        if not (result.get("__interrupt__") or graph.get_state(config).interrupts):
            print(f"Interview {args.interview_id} is not currently waiting on HITL approval.")
            return 1

    decision: dict = {"action": args.action}
    if args.action == "edit":
        if not args.edited_plan:
            print("--edited-plan is required for the edit action")
            return 1
        decision["edited_questions"] = json.loads(args.edited_plan.read_text(encoding="utf-8"))
        decision["notes"] = args.notes or "recruiter edited the question plan"

    result = graph.invoke(Command(resume=decision), config=config)

    final_plan = graph.get_state(config).values.get("question_plan", plan)
    (PREP_DIR / "question_plan.json").write_text(json.dumps(final_plan, indent=2), encoding="utf-8")

    status = graph.get_state(config).values.get("status")
    print(f"Decision '{args.action}' applied. Interview status: {status}")
    if status == "rejected":
        print("Question plan rejected — no interview will start for this interview_id.")
    else:
        print(f"question_plan.json updated (approved_by_human={final_plan.get('approved_by_human')}).")
        print(f"Candidate can now join room 'interview-{args.interview_id}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
