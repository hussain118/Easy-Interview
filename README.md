# FirstRound AI Video Interviewer

Status: **Phase 1 (PREP pipeline) complete.** Live interview, LangGraph
controller, avatar, LiveKit transport, MCP server, and scoring are not
built yet — see `ARCHITECTURE.md` for what's implemented vs. planned.

## What this phase does

Given a job description and a candidate's resume PDF, the PREP pipeline:

1. Parses the JD into structured JSON with GPT (`src/agents/jd_parser.py`)
2. Extracts text from the resume PDF and parses it into structured JSON
   with GPT, without inventing any fact not present in the resume
   (`src/agents/resume_parser.py`)
3. Finds the candidate's GitHub link, pulls real repos/languages/READMEs/
   commits/source-file excerpts via the GitHub REST API, and has GPT
   analyze that real evidence (`src/agents/github_agent.py`)
4. Runs a gap analysis comparing JD needs, resume claims, and GitHub
   evidence (`src/agents/gap_analysis.py`)
5. Plans 12 interview questions grounded in the above, with a
   deterministic Python guardrail that rejects any GitHub-sourced question
   that doesn't cite real evidence (`src/agents/question_planner.py`)

## Install (run it in under 5 steps)

```bash
git clone <your-repo-url>
cd firstround           # or whatever you named the clone
python -m venv .venv
.venv\Scripts\activate       # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Environment setup

Create a `.env` file in the repo root (never commit it — it's already in
`.gitignore`) with these exact variable **names**:

```
OPENAI_API_KEY=...
GOOGLE_API_KEY=...
LIVEKIT_URL=...
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
GITHUB_TOKEN=...
```

- `OPENAI_API_KEY` / `GOOGLE_API_KEY` / `LIVEKIT_API_SECRET` are backend-only
  secrets — never sent to any frontend/browser code.
- `GITHUB_TOKEN` needs no special scopes; a plain classic or fine-grained
  PAT with public-repo read access is enough (used for the 5,000 req/hr
  authenticated rate limit).
- `src/config.py` loads `.env` via `python-dotenv` and exposes
  `check_required_keys()` to verify the required **names** are present —
  it never logs or returns key values.
- This build's `OPENAI_API_KEY` is an **OpenRouter** key (`sk-or-v1-...`),
  so `src/providers/openai_client.py` points the OpenAI SDK at
  `https://openrouter.ai/api/v1` with OpenRouter-style model names
  (`openai/gpt-4o-mini`). If you swap in a real `api.openai.com` key
  instead, set `OPENAI_BASE_URL=https://api.openai.com/v1` in `.env` and
  change `DEFAULT_MODEL` in that file to a plain OpenAI model name.

## Run the PREP pipeline

```bash
python run_prep.py --jd inputs/jd.txt --resume inputs/resume.pdf
```

Writes:
- `output/prep/jd.json`
- `output/prep/resume.json`
- `output/prep/github.json`
- `output/prep/gap_analysis.json` (reference artifact, not a fixed-schema
  requirement, but useful for auditing why questions were chosen)
- `output/prep/question_plan.json`

Each step is skipped and the existing file reused if present (to avoid
unnecessary GPT calls while iterating) — pass `--force` to regenerate
everything from scratch.

`question_plan.json` is written with `"approved_by_human": false`. The
actual human-in-the-loop approve/edit/reject gate now exists as a real
LangGraph `interrupt()` (see "Run the interview graph" below and
`ARCHITECTURE.md`) — the graph genuinely pauses before any question plan
becomes active.

`inputs/jd.txt` and `inputs/resume.pdf` currently hold a **synthetic**
test fixture (a fabricated "Test Candidate" whose GitHub link points to
the real `encode` GitHub organization, so the pipeline exercises the real
GitHub REST API against real repos without attributing anyone's real
personal work to a fictional candidate). Replace both files with a real
JD and a real candidate's resume PDF before the actual graded interview.
Regenerate the fixture anytime with
`python tests/fixtures/generate_synthetic_resume.py`.

## Run the interview graph (Phase 2)

The LangGraph controller (`src/graph.py`) is not wired to real audio yet —
it's driven turn-by-turn via `interrupt()`/`Command(resume=...)`. See
`src/realtime/session_runner.py` for the reference driver loop and
`tests/test_graph.py` for full worked examples (HITL approve/edit/reject,
adaptive follow-up, bluff verification, SQLite checkpoint recovery, etc.),
all run against `MockRealtimeAdapter` — no live API calls, no cost. A real
Gemini Live/LiveKit adapter plugs into the same interface in the next
phase without any change to the graph.

## Tests

```bash
pytest                          # fast tests only (no API calls), 46 tests
RUN_LIVE_TESTS=1 pytest         # also exercises real GPT + GitHub calls
```

Fast tests cover: module imports, PDF text extraction, the GitHub-grounding
guardrail, output-path/schema conformance, and the full LangGraph
controller — graph compilation, normal progression, adaptive routing
(shallow/strong/bluff/off_topic/silence), the 2-follow-up cap, HITL
approve/edit/reject, SQLite checkpoint + dropped-call recovery, invalid
GPT-output normalization, deterministic routing, and the banned-question
guardrail (`tests/test_graph.py`). Live tests (skipped by default, marked
`@pytest.mark.live`) call the real JD parser, resume parser, GitHub agent,
and full PREP pipeline end to end.

## Project layout

```
src/
  config.py              env loading + key-presence checks (no secret printing)
  state.py                typed InterviewState (LangGraph schema)
  graph.py                StateGraph: nodes, conditional edges, SQLite checkpointer
  providers/
    openai_client.py      centralized GPT access (OpenRouter-backed), structured outputs
  agents/
    jd_parser.py, resume_parser.py, github_agent.py,
    gap_analysis.py, question_planner.py, evaluator.py
  nodes/                  one file per graph node (hitl_approval, intro,
                           resume_probe/jd_fit/github_deepdive/scenario,
                           evaluate_answer, candidate_questions, wrap_up, scoring)
  guardrails/
    banned_questions.py    deterministic banned-topic blocking
  realtime/
    adapter.py             abstract RealtimeInterviewAdapter for Prompt 3
    mock_adapter.py         scripted stand-in used by tests
    session_runner.py       reference driver loop tying graph <-> adapter
prompts/                  every system prompt as its own file + ITERATION_NOTES.md
tests/                    pytest suite (fast + live-marked)
inputs/                   jd.txt, resume.pdf (currently synthetic test fixtures)
output/prep/              generated PREP outputs (fixed paths, graded)
run_prep.py               PREP pipeline entrypoint
```

## Known limitations

Phase 1 (PREP):
- `gap_analysis.json` is an extra artifact beyond the assignment's fixed
  schema list; kept because it's a required PREP workflow step and makes
  question grounding auditable.
- Test fixtures are synthetic by design for this phase (see above) — swap
  in the real candidate's resume/GitHub before the graded interview.

Phase 2 (LangGraph controller):
- Not wired to real audio/Gemini Live/LiveKit yet — see `ARCHITECTURE.md`
  for the full list, including the LangGraph `interrupt()` replay gotcha
  this phase surfaced and how it was fixed.
- `scoring` is a stub node (status/timing only) — real competency scoring
  is a later phase.
