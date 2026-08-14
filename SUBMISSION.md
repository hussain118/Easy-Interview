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
  usage logging in place, measured across 102 real calls (evaluator +
  final scorer): **47.2% overall cache hit ratio** (49.5% evaluator, 39.9%
  final scorer) — real, measured, not invented (an earlier isolated
  3-call check had shown 0%; see `ARCHITECTURE.md` for why that changed).
- **LiveKit**: real room creation + candidate/recruiter token minting,
  live-verified against the real LiveKit Cloud project.
- **Gemini Live**: real audio synthesis, output transcription, and
  session-resumption handles, live-verified against the real Google API
  key. Verified working together with LangGraph + GPT for at least one
  real turn (`tests/test_gemini_live_graph_integration_live.py`).
- **Guardrails**: banned-question topics blocked before reaching the
  candidate (all 8 required categories directly unit-tested, plus live
  through the full graph); GitHub-grounding fabrication guardrail
  (tested); **evidence guardrail** — no competency score survives without
  a real, verbatim transcript quote, and this fired for real during
  development (a fabricated/paraphrased "python" competency quote was
  caught and removed — see the guardrail_flags in a real generated
  scorecard).
- **Final scorer + scorecard**: real GPT call, exact §6 schema, tested
  live end to end including the evidence guardrail.
- **5 eval personas**: real per-answer evaluator + real final scorer run
  against all 5 (`evals/run_evals.py`, real GPT calls, not simulated).
  This run is also where a real prompt bug was found and fixed — the
  evaluator was scoring the Bluffer's jargon-heavy, mechanism-free
  answers as "strong." See `evals/results.md` and
  `prompts/ITERATION_NOTES.md`.
- **report.pdf**: real reportlab-generated PDF from the scorecard, tested
  (including a regression test for a real redaction bug — an ISO date was
  being caught by the phone-number regex and blanked out, found by
  actually reading the generated PDF, then fixed).
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
- **MCP server not implemented at all** — the spec lists this as a core
  requirement (§3 item 8); it was explicitly excluded from scope by
  direct instruction in every phase of this build. Stated plainly, not
  hidden.
- The 5-persona ranking doesn't cleanly pass one check: after the
  bluffer-detection fix, the Bluffer persona scores even *below* the
  Weak persona (both `no_hire`, but Bluffer lower) — the spec's literal
  wording has Weak as the single lowest. Written up as an honest,
  arguable edge case in `evals/results.md`, not tuned away to force a
  pass.
- Avatar is a simple SVG face with a speaking-state mouth toggle, not
  per-phoneme viseme lip-sync (acceptable per spec, but worth stating
  plainly).
- The evidence guardrail verifies a quote is *real* (actually said), not
  that the underlying claim is *true* — it cannot fact-check content, only
  confirm it wasn't fabricated by the LLM.

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
the PDF itself, which is not surfaced in any UI. `report.pdf` additionally
redacts phone/address/national-ID-shaped patterns from free-text fields.

## Submission checklist

- [x] Code pushed to a git repo (currently private per your instruction —
      make public before submitting, or confirm the grader has access)
- [ ] `.env` deleted from the machine you submit from / confirmed never
      committed (it's git-ignored throughout this build — verify once
      more with `git ls-files .env` before the final push)
- [ ] Clean-clone test: `git clone`, follow README's install steps on a
      fresh checkout, confirm `run_prep.py` works
- [ ] Code explanation video (1 min) recorded
- [ ] Live demo video (1.5 min) recorded — needs a real live call first
- [ ] Raw recording (8+ min) — needs a real live call first
- [ ] MCP server — **not implemented**, will score 0 on that item; not
      hidden, stated here and in `ARCHITECTURE.md`
- [ ] Barge-in timestamp filled in above
- [ ] Latency numbers filled in above and in `ARCHITECTURE.md`
- [ ] Candidate consent line filled in above
- [ ] Viva scheduled
