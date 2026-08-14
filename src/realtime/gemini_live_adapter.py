"""Gemini Live connection configuration shared by the LiveKit Agents
worker (livekit_agent/interview_worker.py — the real candidate-facing
audio path) and the integration test that exercises Gemini Live directly.

Verified live against the real GOOGLE_API_KEY in this project (see
tests/test_gemini_live_connectivity_live.py):
  - "gemini-2.5-flash-native-audio-latest" is a real, reachable model on
    this key supporting bidiGenerateContent with AUDIO response modality
    (TEXT-only response modality is NOT supported by this model — audio
    interviewers need audio output anyway, so this is not a limitation).
  - output_audio_transcription works (used to build the transcript).
  - session_resumption issues real, usable resumption handles across
    turns (used for the reconnect-on-GoAway strategy).

Caching note (per spec — do NOT use Gemini's explicit context-cache API
here, it does not apply to Live sessions): the only "caching" applicable
to a Live session is (1) keeping the system instruction compact and
stable per session, (2) context_window_compression so a long-running
session doesn't blow its context window, and (3) session_resumption so a
dropped connection reconnects into the *same* conversation instead of
starting cold. All three are configured below.
"""
from __future__ import annotations

from google.genai import types

LIVE_MODEL_NAME = "gemini-2.5-flash-native-audio-latest"
DEFAULT_VOICE = "Puck"


def build_live_connect_config(
    system_instruction: str,
    *,
    resumption_handle: str | None = None,
) -> types.LiveConnectConfig:
    """Builds the LiveConnectConfig for a new (or resumed) Gemini Live
    session. `system_instruction` should be the compact interviewer
    persona text (prompts/live_interviewer.md) — never the resume/JD/
    GitHub evidence or scoring rubric; those are sent turn-by-turn as
    short spoken instructions from LangGraph, not baked into the session.
    """
    return types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=types.Content(parts=[types.Part(text=system_instruction)]),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=DEFAULT_VOICE)
            )
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        # Session continuity strategy (spec requirement): compress the
        # context window so a long interview doesn't exceed Gemini Live's
        # window, and always request a resumption handle so a dropped
        # connection can reconnect into the same conversation rather than
        # restarting the interview from scratch.
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow(),
        ),
        session_resumption=types.SessionResumptionConfig(handle=resumption_handle),
    )
