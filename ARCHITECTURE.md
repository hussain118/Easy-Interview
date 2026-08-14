# Architecture

## Status

This document describes the **target architecture** for the full
assignment and marks clearly what is implemented today (Phase 1: PREP
pipeline, Phase 2: LangGraph interview controller) vs. planned for later
phases. Nothing below is claimed as working unless it's under
"Implemented".

## Component roles

| Component | Role | Status |
|---|---|---|
| **GPT (via OpenRouter)** | Offline analysis/reasoning: JD/resume/GitHub parsing, gap analysis, question planning; live per-answer evaluation (quality/confidence/reason); and post-interview final scoring. The *only* thing that grades a candidate, at any stage. Structured with stable, cacheable system-prompt prefixes throughout. | **Implemented**, including final scoring (`src/agents/scorer.py`). |
| **GitHub REST API** | Real evidence source: repos, languages, READMEs, commits, source-file excerpts for the candidate's actual account. | **Implemented.** |
| **LangGraph** | Authoritative interview controller: typed state, 10 nodes, multiple conditional edges, adaptive follow-up routing, HITL interrupt, SQLite checkpointer for resume-after-drop. | **Implemented** (`src/graph.py`, `src/nodes/`). Driven turn-by-turn via `interrupt()`/`Command(resume=...)`. |
| **SQLite** | LangGraph checkpointer storage — every node transition is durably saved, so a dropped call resumes at the correct node instead of restarting. | **Implemented** (`langgraph-checkpoint-sqlite`, `src/graph.py::get_sqlite_checkpointer`). |
| **Python (deterministic guardrails)** | Validation that doesn't depend on the LLM being honest — GitHub-grounding check, banned-question blocking, GPT-evaluation normalization, follow-up cap enforcement, routing decisions, **and evidence-quote verification for every final score**. | **Implemented** for all of the above, including the evidence guardrail (`src/guardrails/evidence_check.py`) — a score without a real transcript quote cannot survive into `scorecard.json`. |
| **Gemini Live API** | Real-time interviewer: native audio in/out, built-in interruption/barge-in, conversational voice. Never decides answer quality — GPT does, always. | **Implemented** (`livekit_agent/interview_worker.py`, `src/realtime/gemini_live_adapter.py`). Connectivity, audio synthesis, transcription, and session resumption independently verified live. Full audio round-trip through a browser is not verified in this environment (no mic/speaker/browser here) — see "What's verified vs. not" below. |
| **LiveKit** | Real-time transport: the video/audio room, candidate connection, secure participant access, barge-in/turn-detection plumbing. | **Implemented** (`src/realtime/livekit_room.py`, `src/api.py`). Room creation and token minting verified live against the real LiveKit Cloud project. |
| **Avatar (2D)** | Visible AI face, simple viseme-style lip-sync driven by the AI's speaking state. | **Implemented, intentionally simple** (`frontend/candidate.html`) — an SVG face whose mouth toggles open/closed based on LiveKit's `ActiveSpeakersChanged` event (real speaking-state signal, not a fixed animation loop, but not per-phoneme viseme sync either). Priority was working voice/barge-in/transport first, per the spec's own stated priority order. |
| **MCP server** | `>=5` tools exposed to Claude Desktop (get_candidate, get_question_plan, save_score, get_scorecard, list_interviews). | **NOT implemented.** Explicitly excluded from every phase's scope by direct instruction throughout this build. The spec lists it as a core requirement (§3 item 8) — flagging this plainly rather than claiming otherwise. |
| **FastAPI** | Backend API: consent recording, LiveKit token minting, interview status. | **Implemented** (`src/api.py`). No recruiter dashboard UI — recruiter actions are CLI scripts (`run_prep.py`, `run_hitl_approval.py`, `run_scoring.py`). |

## Phase 1 data flow (implemented)

```
inputs/jd.txt ─────► jd_parser (GPT) ─────────────► output/prep/jd.json
inputs/resume.pdf ─► resume_parser (pdfplumber/  ─► output/prep/resume.json
                      pypdf + GPT)
resume.json[github link] ─► github_agent (real   ─► output/prep/github.json
                             GitHub REST + GPT)
jd.json + resume.json     ─► gap_analysis (GPT)   ─► output/prep/gap_analysis.json
  + github.json
jd.json + resume.json     ─► question_planner     ─► output/prep/question_plan.json
  + github.json + gap.json  (GPT + Python
                              grounding guardrail)
```

All GPT calls go through one abstraction (`src/providers/openai_client.py`)
using OpenAI SDK structured outputs (`response_format: json_schema,
strict: true`) so every agent gets back schema-conformant JSON — no
regex/prose parsing of model output anywhere in the pipeline.

### Why GPT is routed through OpenRouter

The provided `OPENAI_API_KEY` is in OpenRouter's key format
(`sk-or-v1-...`), not an official OpenAI key. `openai_client.py` points
the OpenAI SDK's `base_url` at `https://openrouter.ai/api/v1` and uses
OpenRouter-style model names (`openai/gpt-4o-mini`). This is purely a
routing/config decision — same SDK, same structured-output contract, no
behavior change to the rest of the pipeline. See README.md for how to
switch back to a native OpenAI key.

### GitHub grounding guardrail

`src/agents/question_planner.py::validate_github_grounding()` is plain
Python, not an LLM call. It collects every real repo name/full_name,
commit SHA, and sample-file path actually pulled by `github_agent.py`,
then checks that every question with `"source": "github"` has a
`source_reference` containing one of those real tokens, and that there are
at least 3 such questions when GitHub evidence exists. If the model's
first attempt fails this check, `plan_questions_to_file()` retries up to 2
more times with an explicit correction note before giving up and raising
`GitHubGroundingError` — see `prompts/ITERATION_NOTES.md` for the real
failure this caught during testing and how it was fixed.

## Phase 2 — LangGraph interview controller (implemented)

### State object

`InterviewState` (`src/state.py`, a `TypedDict`) is the single source of
truth the graph reads/writes at every node. Fields: `interview_id`;
static context loaded once (`candidate_name`, `role_title`, `jd`,
`resume`, `github_evidence`); the HITL/plan fields (`question_plan`,
`plan_approval_status`, `plan_edits`, `question_queue`); live-progress
fields (`current_phase`, `current_node`, `current_question`,
`current_answer`, `last_evaluation`, `follow_up_count`, `difficulty`);
`transcript`; timing (`start_time_ms`, `elapsed_ms`); `guardrail_flags`;
`next_action`; `status`/`completed`; and three internal turn-taking guard
fields (`awaiting_answer_for`, `pending_question_text`,
`asked_this_turn` — see "A real LangGraph gotcha" below for why these
exist and why they had to be declared schema fields, not ad-hoc dict
keys).

### Nodes (10)

```
hitl_approval → intro → resume_probe → resume_probe_wait → evaluate_answer
                              ↕ (loops back for follow-up/verify/recovery,
                                 or advances — see routing below)
                         → jd_fit → jd_fit_wait ─────────────┘
                         → github_deepdive → github_deepdive_wait ┘
                         → scenario → scenario_wait ───────────────┘
                                                                    ↓
                                          candidate_questions → wrap_up → scoring → END
```

Each of the four topics (`resume_probe`, `jd_fit`, `github_deepdive`,
`scenario`) is actually **two** nodes — `<topic>` (prepare: decide what to
ask, pop the next queued question or generate a follow-up/verify/recovery
probe, append the agent's transcript line) and `<topic>_wait` (nothing but
`interrupt()`, waiting for the candidate's answer). That makes 8 nodes for
the 4 topics, plus `hitl_approval`, `intro`, `evaluate_answer`,
`candidate_questions`, `wrap_up`, `scoring` = **10 nodes total** (spec
requires ≥6).

### Conditional edges

- `hitl_approval → {intro | END}` (`route_after_hitl`): reject ends the
  graph before any interview content is generated; approve/edit both
  proceed to `intro`.
- `<topic> → {<topic>_wait | next_topic}` (`route_after_prepare`, one per
  topic): if the prepare node found something to ask, go wait for the
  answer; if its question queue was already empty, pass straight through
  to the next topic — this is what lets a topic with 0 planned questions
  (e.g. no scenario questions were generated) get silently skipped without
  a dead node visit.
- `evaluate_answer → {resume_probe | jd_fit | github_deepdive | scenario |
  wrap_up}` (`route_after_evaluation`): reads the validated `quality`
  enum + the per-topic follow-up count to decide follow_up / verify /
  recovery / advance, or wrap_up if the time budget is exceeded. This is
  the requirement's most important conditional edge — it's what makes
  shallow answers probe deeper, strong answers raise the bar, and bluffs
  get verified, without any hardcoded linear script.

All routing decisions are made from the validated `quality` string set by
`evaluate_answer_node` (which itself normalizes raw GPT output via
`normalize_evaluation()`) — never from GPT's free-text
`recommended_action` field, and never inside a conditional-edge function
(see gotcha below).

### Adaptive follow-up / difficulty / bluff / recovery

`src/nodes/evaluate_answer.py::evaluate_answer_node` is where the decision
is actually made (not the edge function — see below): `strong` bumps
difficulty one rung (easy→medium→hard) and advances; `good` advances;
`bluff` sets `next_action="verify"`; `shallow` sets `"follow_up"`;
`off_topic`/`unclear` (including silence — an empty answer skips the GPT
call entirely and uses a canned `unclear` evaluation) set `"recovery"`.
Every probe path increments `follow_up_count[topic]`; once it hits
`MAX_FOLLOW_UPS = 2`, the node forces an advance regardless of quality —
this is the hard cap that prevents an infinite loop, enforced in Python,
tested directly (`test_max_two_follow_ups_then_advances`).

Probe question text (follow_up/verify/recovery) is generated
**deterministically** (`src/nodes/_helpers.py::generate_probe_question`),
not via an extra GPT call — cheaper, and testable without mocking an LLM.
Verify-probes reference the original question's `source_reference` (e.g.
"walk me through repo:x, file:y") instead of accusing the candidate of
bluffing.

### HITL gate

`src/nodes/hitl_approval.py` calls `interrupt()` with the full question
plan and genuinely pauses — `graph.invoke()` returns with `__interrupt__`
set and nothing downstream has run. Resuming with
`Command(resume={"action": "approve"})` or `{"action": "edit",
"edited_questions": [...], "notes": "..."}` or `{"action": "reject"}`
drives `route_after_hitl`: approve/edit → `intro` (edit also replaces
`question_plan["questions"]` and records the note in `edits_made`);
reject → `END` with `status="rejected"` and an empty transcript — no
interview content is ever generated for a rejected plan. All three paths
are tested (`test_hitl_approval`, `test_hitl_edit_applies_changes`,
`test_hitl_rejection_stops_before_any_interview`).

### SQLite checkpointing / dropped-call recovery

`get_sqlite_checkpointer()` wraps `langgraph.checkpoint.sqlite.SqliteSaver`
around a real `sqlite3` connection to a file (default
`data/checkpoints.sqlite`, gitignored — it's runtime state, not a
deliverable). Every node transition is persisted keyed by
`config["configurable"]["thread_id"]`. `test_sqlite_checkpoint_and_dropped_call_recovery`
proves the real requirement: build a graph, progress through HITL approval
and one full Q&A turn, discard the Python graph object entirely (simulating
a crashed process), build a **brand-new** graph against the same db file
and thread id, confirm `get_state()` shows the correct paused node/queue
(not START), then resume and confirm the interview continues from exactly
where it left off — `intro` does not re-run, no question is re-asked.

### A real LangGraph gotcha (worth documenting)

Initial implementation had each topic as a single node that both mutated
state (popped the next question, set a "waiting" flag) and then called
`interrupt()`. This intermittently asked two questions before recording
any answer, and misattributed answers to the wrong question. Root cause,
confirmed empirically: LangGraph resumes a node by re-running it and
matching the provided resume value to whichever `interrupt()` call it
hits *next* — by call position, not by which specific pause it was
"meant" for — so any state mutation made before an `interrupt()` call in
a node that gets revisited (our follow-up/next-question cycle) can get
silently redone or skipped on replay. Fix: split each topic into a
prepare node (all mutation, returns normally, so it commits cleanly, no
`interrupt()` inside it) and a wait node (nothing but `interrupt()`, so
replaying it is a no-op). See `src/nodes/_topic_node.py`'s docstring and
`prompts/ITERATION_NOTES.md`.

A related, smaller version of the same lesson: conditional-edge (`path`)
functions in LangGraph are read-only for routing purposes — mutations
made inside one (e.g. incrementing a counter) do **not** persist. All
state-changing decisions (`next_action`, `follow_up_count`, `difficulty`)
were moved into `evaluate_answer_node` itself; `route_after_evaluation`
only reads already-decided state and returns a destination name.

### Realtime interface

`src/realtime/adapter.py` defines `RealtimeInterviewAdapter` (abstract:
`start_session`, `speak`, `stop_speaking`, `receive_candidate_turn`,
`send_instruction`, `end_session`) and `src/realtime/mock_adapter.py` +
`src/realtime/session_runner.py` are the scripted, sync stand-in every
graph test drives against — the graph has **zero** dependency on any real
transport, only on `interrupt()` payloads and resume values.

The real production path (`livekit_agent/interview_worker.py`) does not
literally instantiate `RealtimeInterviewAdapter` — LiveKit Agents'
`AgentSession` is inherently async/event-driven (state-change callbacks,
not a blocking `speak()`/`receive_candidate_turn()` call pair), so forcing
it through that sync interface would add an awkward thread/queue bridge
for no real benefit. Instead the worker achieves the *same* decoupling
principle directly: it never imports anything Gemini-specific into
`src/graph.py` or any node — it only ever reads `interrupt()` payloads
(`{"question": ...}`) off `graph.get_state(config).interrupts` and feeds
`Command(resume=<transcribed answer>)` back in, exactly like the mock
adapter does. Same contract, no forced abstraction mismatch.

## Phase 3 — Live call (Gemini Live + LiveKit)

### What's verified vs. not

Everything below marked **live-verified** was actually run against the
real credentials in `.env` during development (see the referenced test
file) — not just written and assumed to work.

| Piece | Status |
|---|---|
| LiveKit room creation + candidate/recruiter token minting | **Live-verified** — `tests/test_livekit_room_live.py` |
| Gemini Live connection, audio synthesis, output transcription | **Live-verified** — `tests/test_gemini_live_connectivity_live.py` (real audio bytes returned, transcript matched exactly what was asked) |
| Gemini Live session-resumption handles actually issued | **Live-verified** — same file, confirmed across multiple turns |
| LangGraph question selection + Gemini speaking it + GPT evaluating a (scripted) answer, wired together | **Live-verified** — `tests/test_gemini_live_graph_integration_live.py` |
| FastAPI consent → LiveKit token flow | **Live-verified** — `tests/test_api.py` |
| `graph.update_state()` correctly marking a transcript turn `interrupted=true` (the barge-in transcript mechanism) | **Live-verified** (mechanism only, not triggered by a real interruption) — `tests/test_barge_in_transcript_patch.py` |
| `livekit_agent/interview_worker.py` end to end with a real candidate in a real browser | **NOT verified** — this environment has no microphone, speaker, or browser. The worker imports and constructs its `RealtimeModel`/`Agent`/`AgentSession` correctly (`tests/test_interview_worker_imports.py`), but the full audio round-trip through LiveKit (candidate mic → LiveKit → worker → Gemini Live → worker → LiveKit → candidate speaker) has only been exercised piece-by-piece, never as one continuous real call. |
| Barge-in actually cutting off audio mid-sentence in a real call | **NOT verified** — requires a real human speaking over the AI. The mechanism LiveKit Agents uses for this (VAD-based turn detection built into `AgentSession`) is the framework's own responsibility, not custom code here; what *is* custom (marking the transcript) is verified. |
| `frontend/candidate.html` in an actual browser | **NOT verified** — written against LiveKit's documented JS client API (`Room`, `RoomEvent.TrackSubscribed`, `ActiveSpeakersChanged`, `prepareConnection`) and the CDN script URL was confirmed reachable, but never opened in a real browser in this session. |

The honest summary: transport (LiveKit) and brain (Gemini Live) are each
independently proven to work with these exact credentials, and proven to
work *together* with LangGraph and GPT for at least one real turn. What's
unverified is specifically the parts that require a human with a
microphone and a browser — which this coding environment cannot provide.
**Run `python livekit_agent/interview_worker.py dev` plus
`frontend/candidate.html` yourself to complete that verification.**

### How to run the live call

1. `python run_prep.py` (or reuse existing `output/prep/*.json`).
2. `python run_hitl_approval.py --interview-id demo-001 approve` — the
   real HITL gate; the graph genuinely pauses until this runs.
3. `uvicorn src.api:app --reload --port 8000` (backend).
4. `python livekit_agent/interview_worker.py dev` (the AI's side —
   separate long-lived process, standard LiveKit Agents deployment model).
5. Open `frontend/candidate.html?interview_id=demo-001` in a browser,
   consent, join.

### GPT prompt-caching strategy

Both GPT workloads that repeat structurally — the per-answer evaluator
and the final scorer — are structured exactly as required:

```
STABLE PREFIX (prompts/answer_evaluator.md or prompts/final_scorer.md,
                byte-identical every call — this is the cache-eligible part)
  -> role/rubric/quality-or-scoring definitions, fairness rule, evidence
     requirement, guardrail note, output schema description
STATIC INTERVIEW CONTEXT (final scorer only — role, competency list,
                compact resume claims, compact GitHub evidence summary;
                never the raw repository)
DYNAMIC SUFFIX (per-call user message, transcript/answer always LAST)
  -> current question + competency + difficulty + evidence reference
     + candidate answer + last few same-topic transcript turns
     (evaluator), or per-answer evaluations + full transcript (scorer)
     — never the full resume/JD/GitHub JSON, never resent redundantly
```

`src/providers/openai_client.py::structured_completion_with_usage()`
passes a fixed `prompt_cache_key` — `"first-round-answer-evaluator-v1"`
for every evaluator call, `"first-round-final-scorer-v1"` for real-interview
scoring, `"first-round-persona-scorer-v1"` for the synthetic eval-persona
runs (kept separate so eval traffic doesn't mix into production cache
stats) — never containing candidate content, and reads back
`usage.prompt_tokens_details.cached_tokens` from the response.
`src/agents/cache_metrics.py::record()` logs
`{model, purpose, input_tokens, cached_tokens, output_tokens,
cache_hit_ratio}` per call to `output/cache_metrics.jsonl` — numbers and
labels only, never candidate text.

**Cross-candidate isolation**: the ONLY thing that's cache-eligible is the
stable prefix (rubric/schema/instructions, identical for every candidate
by design). Every candidate's resume claims, GitHub evidence, transcript,
and answers are sent fresh in the dynamic suffix on every single call —
never pre-loaded into a shared cache, never persisted across requests
outside each call's own `messages` array. There is no mechanism in this
codebase by which one candidate's dynamic content could be reused for
another candidate; the prefix that *is* shared/cached contains zero
candidate-specific information by construction.

**Measured result** (real, not invented): an early isolated check
(`tests/test_cache_metrics_live.py`, 3 back-to-back evaluator calls, v2
prompt, via OpenRouter) found `cached_tokens = 0` on every call — reported
honestly at the time. Since then, the evaluator prompt grew (v3's "Jargon
vs. specificity" section — see `prompts/ITERATION_NOTES.md`) and the
final scorer's longer stable prefix came online, and both are now reused
across many real calls in the same session (5-persona evals, direct
scorer tests). Aggregate of every real call logged so far
(`src/agents/cache_metrics.py::summarize()` over `output/cache_metrics.jsonl`,
102 calls total):

| Purpose | Calls | Total input tokens | Total cached tokens | Cache hit ratio |
|---|---|---|---|---|
| answer_evaluation | 84 | 124,713 | 61,696 | **49.5%** |
| final_scoring | 18 | 38,208 | 15,232 | **39.9%** |
| **overall** | **102** | **162,921** | **76,928** | **47.2%** |

Read honestly: this is a real, substantial, measured cache hit ratio
achieved through OpenRouter — the earlier 0% result was real too, at that
point in time, with a shorter prompt and only 3 calls; caching evidently
became reliable once the stable prefix was long enough and got reused
enough times in the same session. This table reflects actual accumulated
usage from this development session, not a controlled/isolated benchmark
— re-run `python -c "from src.agents.cache_metrics import summarize; print(summarize())"`
for the current numbers.

### Gemini Live context/continuity strategy (NOT explicit prompt caching)

Per the spec, Gemini Live sessions do **not** use the explicit
context-cache API (that's for the standard `generateContent` API, not
`bidiGenerateContent`/Live sessions). Instead:

1. **Compact system instruction** (`prompts/live_interviewer.md`) — AI
   identity, disclosure, interruption/pacing behavior, and an explicit
   instruction to only ever say what LangGraph tells it to say next.
   Deliberately excludes the resume, JD, GitHub evidence, and scoring
   rubric — those never enter the Gemini session at all; they inform
   GPT's evaluation and LangGraph's question selection instead.
2. **Minimal dynamic instructions per turn** — the worker's `speak()`
   sends only the next question/probe text via `generate_reply()`, not
   accumulated context.
3. **Context-window compression** — `types.ContextWindowCompressionConfig(sliding_window=types.SlidingWindow())`,
   configured in `src/realtime/gemini_live_adapter.py::build_live_connect_config()`
   and passed through the LiveKit `RealtimeModel`.
4. **Session resumption** — every `LiveConnectConfig` requests a
   `session_resumption` handle; live-verified that the API actually
   issues one after each turn (`tests/test_gemini_live_connectivity_live.py`).
   On a `GoAway`/disconnect, the intended reconnect path is: grab the last
   handle received, reconnect with
   `SessionResumptionConfig(handle=last_handle)`, and continue — this
   reconnect path itself is implemented in `build_live_connect_config`'s
   `resumption_handle` parameter but has not been exercised against a
   real forced disconnect (would require deliberately killing a live
   session mid-call).
5. **Interview continuity actually lives in LangGraph + SQLite, not
   Gemini** — even if a Gemini session resets, the interview's question
   position, transcript, follow-up counts, and difficulty are safely on
   disk in the SQLite checkpoint (this is the *real* continuity
   mechanism; Gemini's own session resumption is a secondary layer on
   top of it, not a substitute for it).

## Phase 4 — Scoring, evidence guardrail, evals, report

### Final scorer

`src/agents/scorer.py::score_interview()` — GPT synthesizes a transcript
+ per-answer evaluations (`InterviewState.evaluation_history`, appended
by `evaluate_answer_node` on every turn — Phase 2's node, extended
additively, not rebuilt) into the exact `output/scorecard.json` schema
from §6. `candidate_name`, `role`, `interview_date`, `duration_seconds`,
and `github_grounded_questions_asked` are filled deterministically in
Python — GPT is never asked to state or count them, only to produce
`competencies`, `overall_score`, `recommendation`,
`recommendation_reasoning`, `strengths`, `concerns`, `guardrail_flags`.
`run_scoring.py --interview-id <id>` runs this against a real completed
interview's own LangGraph checkpoint (never against whatever happens to
currently be in `output/prep/*.json`, which could belong to a different
interview by the time scoring runs).

### Evidence guardrail (deterministic, not GPT)

`src/guardrails/evidence_check.py::validate_scorecard_evidence()` — after
GPT returns a scorecard, every competency's `evidence_quote` is checked
(whitespace/case-normalized substring match) against the *real*
transcript. Any competency whose quote doesn't verify is **removed
entirely** from the scorecard (its score cannot count) and a
`evidence_guardrail_rejected:<name>:...` flag is added; `overall_score` is
recalculated from only the surviving competencies. This is not
theoretical — it fired for real during development (`run_scoring.py`
against a real generated interview rejected a "python" competency score
whose quote didn't verify verbatim; see the guardrail_flags in that run).

### Banned-question guardrail

`src/guardrails/banned_questions.py` (built in Phase 3, wired into every
topic node before a question is ever spoken) — directly unit-tested here
against all 8 required categories (age, gender, marital status, religion,
nationality, health/pregnancy, salary history, politics) plus false-positive
checks against legitimate technical questions (`tests/test_banned_questions.py`,
14 tests, all passing).

### Five eval personas

`evals/run_evals.py` runs the *real* pipeline (real per-answer GPT
evaluator for each synthetic answer, then the real GPT final scorer) —
not a hand-simulated result — against all 5 personas
(`evals/personas/*.json`) and writes `evals/results.md`. This is where
the answer_evaluator v2→v3 fix (jargon-vs-specificity, see
`prompts/ITERATION_NOTES.md`) was actually discovered: the first real run
scored the Bluffer persona *above* Average, failing the spec's explicit
"bluffer must land below Average" requirement. After the fix: Strong is
highest (5.0, hire), Nervous lands near Strong (2.5, borderline — the
fairness case working as intended), Bluffer correctly drops below Average
(1.5 vs 2.0). One check still doesn't cleanly pass — Weak (2.0) no longer
scores as the single lowest persona, since Bluffer's confirmed fabrications
now score even lower — written up as an honest, arguable edge case in
`evals/results.md` rather than tuned away to force a clean pass. Full
scorecards for all 5 personas are in that file.

### Report PDF

`src/agents/report_generator.py` (reportlab, no LLM call) reads
`output/scorecard.json` and writes `output/report.pdf` — candidate, role,
duration, every competency's score/quote/reasoning/confidence, strengths,
concerns, recommendation, GitHub-grounded question count, guardrail
flags. Redacts anything matching a phone number, street address, or
national-ID pattern — but only in free-text fields (candidate name,
reasoning, quotes, strengths/concerns/flags), never in structured fields
like `interview_date`/scores/counts. That distinction exists because the
first version over-redacted: a plain ISO date (`2026-08-14`) was being
caught by the phone-number regex and replaced with `[redacted]` in the
generated PDF — caught by actually reading the generated PDF, not
assumed correct (`tests/test_report_generator.py` now covers this
directly, including a regression test for the exact date-corruption bug).

## Latency

Target: <1.2s from candidate-stops-speaking to agent-starts-speaking.
`livekit_agent/interview_worker.py` measures this for real, on every
turn, from LiveKit Agents' own `user_state_changed`
(`speaking` → not `speaking`) and `agent_state_changed`
(→ `speaking`) events — not a guess — and appends each measurement to
`output/latency_measurements.jsonl`. **No measurements exist yet**
because that requires a real candidate turn in a real call, which this
environment cannot produce. Run the live call once (see above) and this
section will be updated with the real numbers from that file, not an
estimate.

## Known limitations

Phase 1 (PREP):
- `question_planner`'s GitHub-grounding correctness depends on GPT
  sampling variance; the Python guardrail + bounded retry (not the prompt
  alone) is what actually enforces the ≥3 requirement — see
  `prompts/ITERATION_NOTES.md`.
- `github_agent.py` only inspects each analyzed repo's root directory for
  sample source files (bounded to 2 files, ~1.2KB excerpt each) to keep
  API usage light; it will miss relevant code nested in subdirectories.
- Resume parsing trusts pdfplumber/pypdf text extraction; a scanned
  image-only PDF with no text layer will fail loudly (`ValueError`) rather
  than silently producing empty output — no OCR fallback is implemented.

Phase 2 (LangGraph controller):
- `scoring` (the graph node) still only finalizes status/timing — the
  real scoring logic lives in the separate `run_scoring.py` step, run
  after the graph reaches END, not inside the graph itself. This is a
  deliberate separation (scoring needs the *complete* transcript, and
  re-running it shouldn't require re-running the interview) but is worth
  naming plainly since the node's name suggests otherwise.
- `candidate_questions` allows exactly one candidate-asked question per
  interview (a single exchange), not an open-ended loop.
- The time-budget safety net (`MAX_INTERVIEW_SECONDS = 1200`) that jumps
  straight to `wrap_up` is a real Python check but has no live test with
  an actual 20-minute run — it's exercised via `time_exceeded()` unit
  logic, not an end-to-end timing test (would make the suite slow).

Phase 3 (live call):
- See "What's verified vs. not" above — the honest short version: every
  individual piece (LiveKit, Gemini Live, GPT, LangGraph) is
  live-verified against real credentials, and proven to work together for
  at least one real turn, but a full continuous real-human call through
  the browser frontend has not been run in this environment.
- No latency numbers exist yet — the measurement code is real and wired
  in, but needs a real call to produce data.
- Avatar is intentionally simple (SVG + open/closed mouth toggle on
  speaking state), not per-phoneme viseme sync — acceptable per the
  spec's own "simple 2D avatar... earns full marks" allowance, and
  consistent with the spec's stated priority order (voice/barge-in/
  transport first, avatar/lip-sync last).
- `frontend/candidate.html` has no automatic reconnect-and-rejoin UI if
  the browser's LiveKit connection itself drops (as opposed to the
  Gemini Live session dropping, which the worker does handle via
  session resumption + the SQLite-backed graph checkpoint) — the
  candidate would need to reload the page and rejoin, which the worker
  supports (it resumes from the existing checkpoint) but isn't automated
  client-side.
- The FastAPI backend has no auth on its endpoints (fine for a local/dev
  deployment behind the assignment's scope; would need real auth before
  any actual production use).

Phase 4 (scoring, evals, report):
- `evals/results.md`'s `weak_is_lowest` check does not cleanly pass — see
  "Five eval personas" above and the failure analysis in that file for
  the honest reasoning (a confidently-fabricating Bluffer now scores
  below an honestly-thin Weak, which is defensible but not what the
  literal "Weak: Lowest" wording states).
- The evidence guardrail only verifies a quote is *real* (actually said);
  it cannot and does not judge whether the underlying technical claim in
  that quote is *true* — a candidate could say something false and back
  it with their own real (false) words, and the guardrail would correctly
  not reject it, because the guardrail's job is narrowly "did they really
  say this," not fact-checking.
- `report.pdf`'s PII redaction is regex-based and necessarily incomplete
  — it catches common phone/address/national-ID *patterns*, not every
  possible PII format; it should not be relied on as the only privacy
  safeguard (the consent flow and "don't collect unnecessary fields in
  the first place" matter more).
- MCP server: not implemented, by explicit instruction across every phase
  of this build, despite being a core spec requirement (§3 item 8). Stated
  plainly here rather than left implicit.
