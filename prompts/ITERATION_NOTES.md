# Prompt iteration notes

## answer_evaluator: v2 → v3 (jargon-vs-specificity fix, diagnosed via the 5-persona evals)

**v1 problem** (discovered running `evals/run_evals.py` for real, not
theorized): fed the "Bluffer" persona's answers through the real
per-answer evaluator (`prompts/answer_evaluator.md`, the v2 from the
Gemini Live phase). Two of four answers — "I architected a full
production-grade RAG pipeline... using a custom-built distributed vector
index I wrote from scratch" and "I use an adaptive chunking algorithm
that dynamically determines optimal chunk boundaries using semantic
similarity clustering combined with a proprietary scoring function" —
were both classified `quality: "strong"`. Downstream, the final scorer
gave the "rag" competency a 4/5 with reasoning calling it "a specific and
technically sound answer." Neither answer names a single real number, a
concrete algorithm step, or a checkable decision — it's fluent technical
vocabulary with nothing underneath. The full 5-persona run scored
bluffer=2.5, *above* both average=2.0 and weak=2.0 — failing the "bluffer
must land below Average" requirement outright.

**Diagnosis**: v2's existing fairness rule already said "fluent delivery
and confident vocabulary are NOT evidence of competence... if the
specifics don't hold up... or contradict the given evidence, that is
bluff" — but that rule only fires when there's evidence to contradict, or
when "specifics don't hold up" is left for the model to judge with no
concrete definition of what "holding up" means. Without an explicit
resume/GitHub fact to contradict (realistic for the first couple of
questions in a real interview, before evidence has been surfaced), the
model had no operational way to distinguish "names real, checkable
mechanisms" from "names impressive-sounding concepts and nothing else" —
so it defaulted to treating jargon density as a proxy for competence.

**v3 change**: added an explicit "Jargon vs. specificity" section to
`prompts/answer_evaluator.md` with side-by-side contrasting examples (the
exact bluffer line vs. a genuinely specific one) and an operational test:
"strip the jargon out — is there a checkable mechanism, number, or
concrete decision left, or would one clarifying 'how exactly' just
produce more of the same vocabulary?" Answers that fail this test are
`bluff` (confident) or `shallow` (tentative), never `strong` — even with
zero contradicting evidence available.

**Measured result**: re-ran the exact same two bluffer answers through
the updated evaluator — both now classify as `bluff` (reasons: "impressive-
sounding claims... lacks specific details on how the architecture works,"
"uses technical jargon without providing specific details on how the
chunking algorithm works"). Re-ran the full 5-persona suite:
bluffer dropped from 2.5 → **1.5**, now correctly below average (2.0) —
`bluffer_below_average` check flipped from FAIL to PASS. See
`evals/results.md` for the full before-is-gone/after table and the one
check that still doesn't pass cleanly (`weak_is_lowest` — the bluffer now
scores even *below* weak, an arguably-defensible but not literally
spec-matching outcome, written up honestly there rather than tuned away).

---

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

## evaluator: v1 → v2 (`answer_evaluator.md`)

**v1** (`prompts/evaluator_v1.md`) classified a single candidate answer
into `strong|good|shallow|bluff|off_topic|unclear` plus a
confidence/reason, scoped to only the current question/competency/
difficulty/evidence-reference/answer/prior-turns — never the full
resume/JD/GitHub JSON. That scoping decision was right and carried
forward unchanged into v2.

**What v1 got wrong, diagnosed while adding prompt-caching support**: the
realtime phase requires calling the evaluator once per candidate answer,
many times per interview, and the spec requires structuring those calls
so the system-prompt portion is a stable, cacheable prefix (identical
bytes across calls) with only the per-turn content varying. v1's system
prompt was short (a few short paragraphs, ~250 words) — nowhere near
OpenAI's ~1024-token minimum for automatic prompt caching to engage even
in principle, and it didn't spell out the rubric/fairness/evidence rules
in enough structural detail to be confident the model was applying them
consistently call to call.

**What changed in v2** (`prompts/answer_evaluator.md`): expanded the
system prompt into explicit labeled sections — quality-label definitions,
a dedicated "fairness rule" section (nervous-but-correct must score on
technical content, not delivery; confident-but-wrong is still bluff), an
"evidence requirement" section, a guardrail note (evaluator never writes
candidate-facing text or picks the graph edge), and an explicit output
contract — long enough to be a meaningful, cacheable prefix, and
structurally clearer for the model to follow. `src/agents/evaluator.py`
now calls `structured_completion_with_usage()` with a fixed
`prompt_cache_key="first-round-answer-evaluator-v1"` (never includes the answer
text) and logs `{input_tokens, cached_tokens, output_tokens}` via
`src/agents/cache_metrics.py` after every call.

**Measured result** (`tests/test_cache_metrics_live.py`, 3 consecutive
live calls with the byte-identical v2 system prompt, run through
OpenRouter): `input_tokens` totaled 3218 (~1072/call), **`cached_tokens`
was 0 on every call**. Honest reading: this is a real, measured null
result, not a success — most likely because (a) ~1072 tokens/call is
right at or under the threshold where automatic caching reliably engages,
and/or (b) OpenRouter's routing to the underlying provider may not
preserve or surface `prompt_tokens_details.cached_tokens` the way calling
`api.openai.com` directly would. The caching *plumbing* (stable-prefix
structuring, `prompt_cache_key`, usage logging) is real and in place;
whether it actually saves tokens through this specific provider path is
unproven and documented as such in `ARCHITECTURE.md` rather than assumed.
`test_routing_ignores_recommended_action_uses_quality_only` still confirms
the separate, load-bearing behavior carried over from v1: routing reads
only the validated `quality` enum, never the model's free-text
`recommended_action`.

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
