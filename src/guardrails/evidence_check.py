"""Deterministic (non-LLM) guardrail: a competency score is only valid if
its evidence_quote is a real, verbatim (whitespace/case-normalized)
excerpt from the actual transcript. Requirement #9(b) / §7 scoring
guardrail: "no score without a transcript quote."

GPT produces the score + quote; this module is the Python check that
decides whether to trust it — the LLM being convincing is never enough.
"""
from __future__ import annotations

import re
from typing import Any


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def quote_found_in_transcript(quote: str, transcript: list[dict[str, Any]]) -> bool:
    """True if `quote` is a verbatim (normalized) substring of something
    actually said in the transcript (by either speaker — an evidence
    quote grounding a competency can legitimately be the candidate's own
    words, most commonly, but the check doesn't hardcode speaker so a
    quote spanning an agent question + implied context isn't falsely
    rejected).
    """
    quote_norm = _normalize(quote)
    if not quote_norm:
        return False
    for turn in transcript:
        if quote_norm in _normalize(turn.get("text", "")):
            return True
    return False


def validate_scorecard_evidence(
    scorecard: dict[str, Any], transcript: list[dict[str, Any]]
) -> dict[str, Any]:
    """Returns a new scorecard dict with any competency whose evidence_quote
    doesn't verify against the transcript REMOVED from "competencies" (its
    score cannot count) and a guardrail_flags entry added explaining why.
    overall_score is recalculated from only the competencies that survive.
    Never mutates the input in place.
    """
    scorecard = dict(scorecard)
    kept: list[dict[str, Any]] = []
    flags = list(scorecard.get("guardrail_flags") or [])

    for comp in scorecard.get("competencies", []):
        quote = comp.get("evidence_quote", "")
        if quote_found_in_transcript(quote, transcript):
            kept.append(comp)
        else:
            flags.append(
                f"evidence_guardrail_rejected:{comp.get('name', 'unknown')}: "
                f"evidence_quote not found verbatim in transcript"
            )

    scorecard["competencies"] = kept
    scorecard["guardrail_flags"] = flags
    scorecard["overall_score"] = (
        round(sum(c["score"] for c in kept) / len(kept), 2) if kept else 0.0
    )
    return scorecard
