# Submission

**Repo**: (add your GitHub repo link here before submitting)
**Videos**: (add unlisted YouTube/Drive/Loom links here — code explanation, demo, raw recording)

## JD chosen

Junior AI Engineer — Northwind Labs, Karachi (0–2 yrs). See `inputs/jd.txt`.
System still accepts any JD as input (`run_prep.py --jd <path>`).

## What works (verified, not just claimed)

- **PREP pipeline**: JD/resume parsing, real GitHub REST evidence
  collection, gap analysis, 12-question plan with ≥3 real GitHub-grounded
  questions, deterministic guardrail rejecting fabricated grounding.
- **LangGraph controller**: 10 nodes, typed state, adaptive follow-up
  (max 2, tested), strong→harder/bluff→verify/off-topic→recovery routing,
  genuine HITL pause (approve/edit/reject all tested), SQLite
  checkpoint + dropped-call recovery (tested: kill the graph object,
  rebuild against the same DB/thread, confirm it resumes mid-interview,
  not from START).
- **GPT answer evaluation**: structured quality/confidence/reason/
  recommended_action; routing uses only the validated `quality` enum,
  never the model's free-text suggestion (tested directly).
- **GPT prompt caching**: stable-prefix structure + `prompt_cache_key` +
  usage logging in place and measured live; measured `cached_tokens = 0`
  across 3 identical-prefix calls via OpenRouter — reported honestly as a
  real null result, not hidden or invented as a percentage.
- **LiveKit**: real room creation + candidate/recruiter token minting,
  live-verified against the real LiveKit Cloud project.
- **Gemini Live**: real audio synthesis, output transcription, and
  session-resumption handles, live-verified against the real Google API
  key. Verified working together with LangGraph + GPT for at least one
  real turn (`tests/test_gemini_live_graph_integration_live.py`).
- **Guardrails**: banned-question topics blocked before reaching the
  candidate (tested against a deliberately-banned question, including
  live through the full graph); GitHub-grounding fabrication guardrail
  (tested).
- **Consent flow**: FastAPI endpoint records a written consent statement
  + timestamp before any LiveKit token is issued; token issuance blocked
  without it (tested).

## What is broken / not done (honest)

- **No real human has done a full live call through this yet.** Every
  backend piece is independently live-verified against real credentials
  (see `ARCHITECTURE.md`'s verification table), but this coding
  environment has no microphone, speaker, or browser, so the actual
  candidate-joins-and-talks flow, barge-in cutting off mid-sentence, and
  the 8-minute raw recording have not been produced yet. **This still
  needs to be run by a human** — see `ARCHITECTURE.md` → "How to run the
  live call" for the exact 5 commands.
- Final competency scoring (`output/scorecard.json`, evidence-quote
  guardrail) and the PDF report are not implemented — later phase.
- MCP server not implemented — explicitly out of scope for the phases
  built so far.
- Avatar is a simple SVG face with a speaking-state mouth toggle, not
  per-phoneme viseme lip-sync (acceptable per spec, but worth stating
  plainly).
- GPT prompt caching shows 0 measured cache hits through OpenRouter (see
  above) — the mechanism is real, the savings aren't proven.

## Barge-in timestamp

Not yet available — requires the real human call described above.
**TODO: fill in after running the live call**: `HH:MM:SS` in the raw
recording where the candidate interrupts and the AI stops.

## Latency

Not yet measured — requires a real call. `livekit_agent/interview_worker.py`
logs every candidate-stop → agent-start measurement to
`output/latency_measurements.jsonl` in real time; `ARCHITECTURE.md`'s
Latency section will be updated with the real numbers once that file has
data. **TODO: fill in after running the live call.**

## Avatar used

Simple 2D SVG face (`frontend/candidate.html`), mouth toggles open/closed
based on LiveKit's real `ActiveSpeakersChanged` signal.

## Bonus attempted

Recruiter live-join (silent LiveKit observer token,
`GET /interviews/{id}/recruiter-token` in `src/api.py`) — token minting
implemented and live-verified; the recruiter-side UI to actually join and
inject a question mid-call is not built.

## Candidate consent line

**TODO — fill in after the real interview**: paste the candidate's
written consent (e.g. a screenshot reference or quoted message) agreeing
to be recorded and to have the recording submitted for grading. The
consent statement shown to them (and recorded with a timestamp in
`output/consent/<interview_id>.json`) is:

> "I consent to this interview being recorded (audio and video) and to
> that recording being submitted for grading/evaluation purposes. I
> understand I am speaking with an AI interviewer, not a human."

## Privacy / redaction

No national ID, home address, or phone number fields are collected or
displayed anywhere in the prep pipeline, frontend, or consent record —
only candidate name and (from the resume) whatever contact info was on
the PDF itself, which is not surfaced in any UI.
