"""Deterministic (non-LLM) guardrail: blocks banned question topics before
they would ever reach the candidate. Requirement #9(a) in the spec.
"""
from __future__ import annotations

import re

BANNED_PATTERNS: dict[str, re.Pattern] = {
    "age": re.compile(r"\bhow old are you\b|\byour age\b|\bdate of birth\b|\bbirth ?year\b", re.I),
    "gender": re.compile(r"\byour gender\b|\bare you (a )?(man|woman|male|female)\b", re.I),
    "marital_status": re.compile(r"\bmarital status\b|\bare you married\b|\bsingle or married\b", re.I),
    "religion": re.compile(r"\byour religion\b|\bwhat religion\b|\bare you (a )?(muslim|christian|hindu|jewish|atheist)\b", re.I),
    "nationality": re.compile(r"\byour nationality\b|\bwhat.?s your nationality\b|\bwhere are you from originally\b", re.I),
    "health_pregnancy": re.compile(r"\bare you pregnant\b|\byour health condition\b|\bany disabilit(y|ies)\b|\bmedical condition\b", re.I),
    "salary_history": re.compile(r"\bcurrent salary\b|\bprevious salary\b|\bsalary history\b|\bhow much (did|do) you (get paid|earn)\b", re.I),
    "politics": re.compile(r"\bwho did you vote for\b|\byour political (view|affiliation|party)\b|\bwhich party do you support\b", re.I),
}


def check_question(text: str) -> list[str]:
    """Returns the list of banned categories the question text matches (empty = clean)."""
    return [category for category, pattern in BANNED_PATTERNS.items() if pattern.search(text or "")]


def is_banned(text: str) -> bool:
    return bool(check_question(text))


SAFE_FALLBACK_QUESTION = (
    "Let's move on — can you walk me through a technical decision you made "
    "on one of your recent projects and why you made it?"
)
