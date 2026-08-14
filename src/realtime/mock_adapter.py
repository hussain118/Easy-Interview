"""In-memory scripted adapter used by tests and the CLI runner until the
real Gemini Live/LiveKit adapter is built. No network, no audio.
"""
from __future__ import annotations

from src.realtime.adapter import RealtimeInterviewAdapter


class MockRealtimeAdapter(RealtimeInterviewAdapter):
    def __init__(self, scripted_answers: list[str] | None = None):
        self.scripted_answers = list(scripted_answers or [])
        self.spoken: list[str] = []
        self.session_active = False

    def start_session(self, interview_id: str) -> None:
        self.session_active = True

    def speak(self, text: str) -> None:
        self.spoken.append(text)

    def stop_speaking(self) -> None:
        pass

    def receive_candidate_turn(self) -> str:
        if self.scripted_answers:
            return self.scripted_answers.pop(0)
        return ""

    def send_instruction(self, text: str) -> None:
        pass

    def end_session(self) -> None:
        self.session_active = False
