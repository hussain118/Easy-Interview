"""PREP pipeline entrypoint.

    python run_prep.py --jd inputs/jd.txt --resume inputs/resume.pdf

Runs: parse_jd -> parse_resume -> github_agent -> gap_analysis ->
question_planner, writing each result to output/prep/*.json per the
assignment's fixed paths.

Steps are skipped and the existing file reused if it's already present,
to avoid unnecessary GPT calls during iteration. Pass --force to
regenerate everything.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.config import check_required_keys
from src.agents.jd_parser import parse_jd_file
from src.agents.resume_parser import parse_resume_file
from src.agents.github_agent import build_github_profile
from src.agents.gap_analysis import run_gap_analysis_to_file
from src.agents.question_planner import plan_questions_to_file, GitHubGroundingError

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output" / "prep"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the FirstRound PREP pipeline")
    parser.add_argument("--jd", type=Path, default=ROOT / "inputs" / "jd.txt")
    parser.add_argument("--resume", type=Path, default=ROOT / "inputs" / "resume.pdf")
    parser.add_argument("--force", action="store_true", help="Regenerate all steps")
    args = parser.parse_args()

    key_status = check_required_keys(["OPENAI_API_KEY", "GITHUB_TOKEN"])
    missing = [k for k, present in key_status.items() if not present]
    if missing:
        print(f"Missing required environment variables: {missing}. Check your .env file.")
        return 1

    jd_out = OUTPUT_DIR / "jd.json"
    resume_out = OUTPUT_DIR / "resume.json"
    github_out = OUTPUT_DIR / "github.json"
    gap_out = OUTPUT_DIR / "gap_analysis.json"
    plan_out = OUTPUT_DIR / "question_plan.json"

    if args.force or not jd_out.exists():
        print(f"[1/5] Parsing JD from {args.jd} ...")
        jd_json = parse_jd_file(args.jd, jd_out)
    else:
        print(f"[1/5] Reusing existing {jd_out}")
        jd_json = _load(jd_out)

    if args.force or not resume_out.exists():
        print(f"[2/5] Parsing resume from {args.resume} ...")
        resume_json = parse_resume_file(args.resume, resume_out)
    else:
        print(f"[2/5] Reusing existing {resume_out}")
        resume_json = _load(resume_out)

    if args.force or not github_out.exists():
        print("[3/5] Collecting GitHub evidence ...")
        github_json = build_github_profile(resume_json, jd_json, github_out)
    else:
        print(f"[3/5] Reusing existing {github_out}")
        github_json = _load(github_out)

    if args.force or not gap_out.exists():
        print("[4/5] Running gap analysis ...")
        gap_json = run_gap_analysis_to_file(jd_json, resume_json, github_json, gap_out)
    else:
        print(f"[4/5] Reusing existing {gap_out}")
        gap_json = _load(gap_out)

    print("[5/5] Planning interview questions ...")
    try:
        plan_questions_to_file(jd_json, resume_json, github_json, gap_json, plan_out)
    except GitHubGroundingError as e:
        print(f"GitHub grounding guardrail rejected the generated plan: {e}")
        return 1

    print(f"\nPREP complete. Outputs written to {OUTPUT_DIR}")
    print("NOTE: question_plan.json has approved_by_human=false — recruiter HITL "
          "approval is a separate step (not yet implemented in this phase).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
