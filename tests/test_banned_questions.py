"""Direct unit coverage of every banned category the guardrail must block
before a question ever reaches the candidate (spec requirement #9(a)).
No network calls.
"""
from __future__ import annotations

import pytest

from src.guardrails.banned_questions import SAFE_FALLBACK_QUESTION, check_question, is_banned

BANNED_EXAMPLES = [
    ("age", "How old are you?"),
    ("gender", "What is your gender?"),
    ("marital_status", "What is your marital status?"),
    ("religion", "What religion do you practice?"),
    ("nationality", "What is your nationality?"),
    ("health_pregnancy", "Are you pregnant?"),
    ("salary_history", "What is your current salary?"),
    ("politics", "Who did you vote for?"),
]

ALLOWED_EXAMPLES = [
    "Tell me about a project you built.",
    "How would you design a RAG pipeline?",
    "Walk me through your Git workflow.",
    "What is the age of the codebase you worked on?",  # "age" of codebase, not the person
]


@pytest.mark.parametrize("category,question", BANNED_EXAMPLES)
def test_banned_category_is_blocked(category, question):
    matched = check_question(question)
    assert category in matched
    assert is_banned(question)


@pytest.mark.parametrize("question", ALLOWED_EXAMPLES)
def test_legitimate_technical_question_not_blocked(question):
    assert not is_banned(question), f"False positive on legitimate question: {question!r}"


def test_safe_fallback_question_is_itself_not_banned():
    assert not is_banned(SAFE_FALLBACK_QUESTION)


def test_check_question_returns_all_matched_categories_for_multi_violation():
    matched = check_question("How old are you and what is your religion?")
    assert "age" in matched
    assert "religion" in matched
