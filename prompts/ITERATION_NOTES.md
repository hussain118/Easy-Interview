# Prompt iteration notes

## question_planner: v1 → v2

**What v1 got wrong.** v1's github-grounding rule ("at least 3 questions
must have source=github...") was stated once, in the middle of a bulleted
list, alongside five other rules of equal visual weight. During testing
against the `run_prep.py` pipeline (synthetic resume fixture, real GitHub
org `encode`) the model produced only **1** github-sourced question on the
first real run, and **2** on a repeat run at the same temperature — never
reliably hitting the required 3, even though the underlying GitHub evidence
(5 analyzed repos with READMEs and commits) clearly supported it. The
deterministic Python guardrail (`validate_github_grounding` in
`src/agents/question_planner.py`) correctly caught both shortfalls and
refused to write `question_plan.json` rather than silently accepting a
plan that didn't meet the assignment's grounding requirement — which is
the guardrail working as intended, but it meant the pipeline couldn't
complete.

Root cause was twofold:
1. **Evidence was thin at first.** The very first test used `octocat`
   (GitHub's demo account), whose repos are near-empty templates — 0-780
   char READMEs, no real source files. There genuinely wasn't enough
   material for 3 honest github-grounded questions, and the model (and
   guardrail) were right not to fabricate one. This wasn't a prompt bug —
   it was tested against the wrong kind of data. Fixed by switching the
   test fixture to a real account (`encode`, a real Python org) with
   substantive repos, and by having `github_agent.py` additionally pull a
   couple of real source-file excerpts per repo (`fetch_sample_source_files`),
   not just READMEs and commit messages, so there's more real material to
   ground questions in.
2. **Even with rich evidence, the instruction wasn't salient enough.**
   With `encode`'s repos as evidence, v1 still undershot the count
   (1-2 instead of 3+) on some runs — the hard requirement was present but
   buried, competing with five other bullet points for the model's
   attention.

**What changed in v2** (`prompts/question_planner_v2.md`):
- Moved the "≥3 github-sourced questions" rule to a standalone paragraph
  at the very top of the prompt, labeled `HARD REQUIREMENT, CHECKED
  PROGRAMMATICALLY`, and asked the model to count its own github-sourced
  questions before returning.
- Explicitly told the model that `sample_files` (real source excerpts) are
  available and preferred over README-only references, since a file-path
  or commit reference is harder to fake and more interview-worthy.
- Added a `regeneration_instruction` input field: if a first pass fails
  the guardrail, `plan_questions_to_file()` (in
  `src/agents/question_planner.py`) retries up to 2 more times, each time
  telling the model exactly which check it failed and by how much, rather
  than blindly resampling.

**Result after the fix**: on the next full pipeline run, the plan came
back with **4** github-sourced questions (`django-rest-framework` commit,
`rest-framework-tutorial/manage.py`, `databases/setup.py`,
`dashboard/example.py`), all validated against real evidence, guardrail
passed on the first attempt — see `output/prep/question_plan.json`.

**Honesty note**: this is model-variability behavior, not something a
prompt can 100% guarantee deterministically. That's exactly why the
Python-side guardrail + bounded retry exists rather than trusting the
prompt alone — the prompt reduces how often the retry path is needed, the
guardrail is what actually enforces the requirement.

---

## evaluator: v1

`prompts/evaluator_v1.md` classifies a single candidate answer into
`strong|good|shallow|bluff|off_topic|unclear` plus a confidence/reason.
Deliberately scoped narrow: it receives only the current question,
competency, difficulty, the evidence reference the question was grounded
in, the candidate's answer, and a few recent prior turns on the same
topic — never the full resume/JD/GitHub JSON — both to keep tokens down
and because sending the whole GitHub evidence blob would let the model
"grade" against evidence the candidate never demonstrated in *this*
answer.

One explicit instruction worth calling out since it's easy to get wrong:
the prompt tells the model its `recommended_action` is only a suggestion
the system "may not follow literally." This is intentional — routing is
decided in Python (`src/nodes/evaluate_answer.py`) purely from the
validated `quality` enum, never from `recommended_action`, per the spec's
"do not let arbitrary LLM text directly select a graph node" requirement.
`test_routing_ignores_recommended_action_uses_quality_only` asserts this
directly (quality=good + recommended_action=follow_up still advances).
Still v1 — no live-traffic diagnosed failure yet to justify a v2; all
graph tests mock this call, so its real-world calibration (e.g. is
"nervous but correct" reliably scored near "strong" per persona #5 in
§9?) is unverified until the eval-personas phase.

---

## jd_parser, resume_parser, github_analysis, gap_analysis: v1

These prompts (`prompts/jd_parser_v1.md`, `prompts/resume_parser_v1.md`,
`prompts/github_analysis_v1.md`, `prompts/gap_analysis_v1.md`) are still
on v1 — they produced correctly-shaped, evidence-grounded output against
the synthetic test fixture on the first attempt (verified in
`output/prep/jd.json`, `resume.json`, `github.json`, `gap_analysis.json`
and the corresponding pytest cases), so no diagnosed failure has forced an
iteration yet. They will get real v1→v2 notes here if/when a real
candidate's messier resume or a different JD role surfaces an actual
problem (e.g. a multi-column PDF that confuses extraction, or a resume
with no GitHub link at all).
