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
| **GPT (via OpenRouter)** | Offline analysis/reasoning: JD/resume/GitHub parsing, gap analysis, question planning, and — live — the *only* thing that grades a candidate answer (quality/confidence/reason). Structured with a stable, cacheable system-prompt prefix. | **Implemented.** Final competency scoring (scorecard.json) is not yet. |
| **GitHub REST API** | Real evidence source: repos, languages, READMEs, commits, source-file excerpts for the candidate's actual account. | **Implemented.** |
| **LangGraph** | Authoritative interview controller: typed state, 10 nodes, multiple conditional edges, adaptive follow-up routing, HITL interrupt, SQLite checkpointer for resume-after-drop. | **Implemented** (`src/graph.py`, `src/nodes/`). Driven turn-by-turn via `interrupt()`/`Command(resume=...)` — see below. Not yet wired to real audio. |
| **SQLite** | LangGraph checkpointer storage — every node transition is durably saved, so a dropped call resumes at the correct node instead of restarting. | **Implemented** (`langgraph-checkpoint-sqlite`, `src/graph.py::get_sqlite_checkpointer`). |
| **Python (deterministic guardrails)** | Validation that doesn't depend on the LLM being honest — GitHub-grounding check, banned-question blocking, GPT-evaluation normalization, follow-up cap enforcement, routing decisions. | **Implemented** for all of the above. "No score without a quote" guardrail comes with the scoring phase. |
| **Gemini Live API** | Real-time interviewer: native audio in/out, built-in interruption/barge-in, conversational voice. Never decides answer quality. | **Implemented** (`livekit_agent/interview_worker.py`, `src/realtime/gemini_live_adapter.py`). Connectivity, audio synthesis, transcription, and session resumption independently verified live. Full audio round-trip through a browser is not verified in this environment (no mic/speaker/browser here) — see "What's verified vs. not" below. |
| **LiveKit** | Real-time transport: the video/audio room, candidate connection, secure participant access, barge-in/turn-detection plumbing. | **Implemented** (`src/realtime/livekit_room.py`, `src/api.py`). Room creation and token minting verified live against the real LiveKit Cloud project. |
| **Avatar (2D)** | Visible AI face, simple viseme-style lip-sync driven by the AI's speaking state. | **Implemented, intentionally simple** (`frontend/candidate.html`) — an SVG face whose mouth toggles open/closed based on LiveKit's `ActiveSpeakersChanged` event (real speaking-state signal, not a fixed animation loop, but not per-phoneme viseme sync either). Priority was working voice/barge-in/transport first, per the spec's own stated priority order. |
| **MCP server** | Future `>=5` tools exposed to Claude Desktop. | **Not implemented** — explicitly out of scope for this phase. |
| **FastAPI** | Backend API: consent recording, LiveKit token minting, interview status. | **Implemented** (`src/api.py`). No recruiter dashboard UI — recruiter actions are CLI scripts (`run_prep.py`, `run_hitl_approval.py`). |

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

Every evaluator request is structured exactly as required:

```
STABLE PREFIX (prompts/answer_evaluator.md, byte-identical every call)
  -> rubric, quality-label definitions, fairness rule, evidence
     requirement, guardrail note, output schema description
DYNAMIC SUFFIX (per-call user message)
  -> current question + competency + difficulty + evidence reference
     + candidate answer + last few same-topic transcript turns
     (never the full resume/JD/GitHub JSON, never the full transcript)
```

`src/providers/openai_client.py::structured_completion_with_usage()`
passes a fixed `prompt_cache_key="interview-evaluator-v1"` (never
contains candidate content) and reads back
`usage.prompt_tokens_details.cached_tokens` from the response.
`src/agents/cache_metrics.py::record()` logs
`{model, purpose, input_tokens, cached_tokens, output_tokens,
cache_hit_ratio}` per call to `output/cache_metrics.jsonl` — numbers and
labels only, never candidate text.

**Measured result** (`tests/test_cache_metrics_live.py`, 3 consecutive
live calls, identical stable prefix, via OpenRouter): `input_tokens`
totaled 3218 (~1072/call), **`cached_tokens` was 0 on every call.** This
is a real, reported null result — see `prompts/ITERATION_NOTES.md`
("evaluator: v1 → v2") for the likely causes (prefix length near the
automatic-caching threshold; OpenRouter's routing to the underlying
provider may not surface `prompt_tokens_details.cached_tokens` the way a
direct `api.openai.com` call would). The caching *structure* is real and
in place; the *savings* through this specific provider path are not
proven, and this document does not claim they are.

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
- Cache-hit ratio for the GPT evaluator measured 0 in testing (see GPT
  prompt-caching strategy above) — the structure is correct but the
  provider path (OpenRouter) hasn't been shown to actually save tokens.
- The FastAPI backend has no auth on its endpoints (fine for a local/dev
  deployment behind the assignment's scope; would need real auth before
  any actual production use).
