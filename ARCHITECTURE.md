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
| **GPT (via OpenRouter)** | Offline analysis/reasoning: JD/resume/GitHub parsing, gap analysis, question planning, and — live — per-answer evaluation (quality/confidence/reason). | **Implemented.** Final competency scoring (scorecard.json) is not yet. |
| **GitHub REST API** | Real evidence source: repos, languages, READMEs, commits, source-file excerpts for the candidate's actual account. | **Implemented.** |
| **LangGraph** | Authoritative interview controller: typed state, 10 nodes, multiple conditional edges, adaptive follow-up routing, HITL interrupt, SQLite checkpointer for resume-after-drop. | **Implemented** (`src/graph.py`, `src/nodes/`). Driven turn-by-turn via `interrupt()`/`Command(resume=...)` — see below. Not yet wired to real audio. |
| **SQLite** | LangGraph checkpointer storage — every node transition is durably saved, so a dropped call resumes at the correct node instead of restarting. | **Implemented** (`langgraph-checkpoint-sqlite`, `src/graph.py::get_sqlite_checkpointer`). |
| **Python (deterministic guardrails)** | Validation that doesn't depend on the LLM being honest — GitHub-grounding check, banned-question blocking, GPT-evaluation normalization, follow-up cap enforcement, routing decisions. | **Implemented** for all of the above. "No score without a quote" guardrail comes with the scoring phase. |
| **Gemini Live API** | Future real-time interviewer: native audio in/out, built-in interruption/barge-in, conversational voice. | **Not implemented yet.** `src/realtime/adapter.py` defines the interface it will implement. |
| **LiveKit** | Future real-time transport: the video/audio room, candidate connection, secure participant access. | **Not implemented yet.** |
| **Avatar (2D)** | Future visible AI face, viseme lip-sync driven by the TTS stream. | **Not implemented yet.** |
| **MCP server** | Future `>=5` tools (get_candidate, get_question_plan, save_score, get_scorecard, list_interviews) exposed to Claude Desktop. | **Not implemented yet.** |
| **FastAPI** | Future backend API tying the above together for the recruiter dashboard and candidate interview page. | **Not implemented yet.** |

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

### Realtime interface (for the next phase)

`src/realtime/adapter.py` defines `RealtimeInterviewAdapter` (abstract:
`start_session`, `speak`, `stop_speaking`, `receive_candidate_turn`,
`send_instruction`, `end_session`). The graph has **zero** dependency on
it — it only ever produces `interrupt()` payloads (`{"question": ...}`)
and consumes resume values (answer text). `src/realtime/session_runner.py`
shows the intended driver loop: on each interrupt, call
`adapter.speak(question)` then `adapter.receive_candidate_turn()`, feed
that back via `Command(resume=...)`. `src/realtime/mock_adapter.py` is a
scripted in-memory stand-in used by every graph test — Prompt 3 replaces
it with a real Gemini Live/LiveKit adapter without touching `src/graph.py`
or any node.

## Latency

Not applicable yet — no real-time audio path exists in this phase. Will be
measured (candidate-stops-speaking → agent-starts-speaking, target <1.2s)
once the Gemini Live + LiveKit integration is built, and reported here
with a real number, not a guess.

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
- Not wired to real audio yet — everything is tested via
  `MockRealtimeAdapter` and direct `Command(resume=...)` calls. Barge-in
  (mid-sentence interruption) is a Phase 3 concern since it requires an
  actual audio stream to interrupt.
- `scoring` is a stub node — it finalizes status/timing only. Real
  per-competency scoring with evidence quotes is a later phase.
- The "no score without a transcript quote" guardrail isn't implemented
  yet (no scoring exists to guard).
- `candidate_questions` allows exactly one candidate-asked question per
  interview (a single exchange), not an open-ended loop.
- The time-budget safety net (`MAX_INTERVIEW_SECONDS = 1200`) that jumps
  straight to `wrap_up` is a real Python check but has no live test with
  an actual 20-minute run — it's exercised via `time_exceeded()` unit
  logic, not an end-to-end timing test (would make the suite slow).
