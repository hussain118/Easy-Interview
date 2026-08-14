"""Abstract realtime interview transport, implemented for real in a later
phase (Gemini Live for voice, LiveKit for transport). The graph itself
never imports this — it communicates purely through interrupt()/resume
payloads (see src/nodes/*.py), so swapping in a real implementation here
requires no graph changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class RealtimeInterviewAdapter(ABC):
    @abstractmethod
    def start_session(self, interview_id: str) -> None:
        """Open the realtime room/session for this interview."""

    @abstractmethod
    def speak(self, text: str) -> None:
        """Have the AI interviewer say `text` (voice + avatar, later phase)."""

    @abstractmethod
    def stop_speaking(self) -> None:
        """Barge-in: stop the AI mid-sentence when the candidate interrupts."""

    @abstractmethod
    def receive_candidate_turn(self) -> str:
        """Block until the candidate finishes a turn; return the transcript text."""

    @abstractmethod
    def send_instruction(self, text: str) -> None:
        """Send a non-spoken system instruction to the realtime model (e.g.
        persona/context updates) without it being spoken aloud.
        """

    @abstractmethod
    def end_session(self) -> None:
        """Close the realtime room/session."""
