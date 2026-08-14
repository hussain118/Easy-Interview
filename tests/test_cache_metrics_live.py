"""Live measurement of GPT prompt-cache behavior for the evaluator. Skipped
by default (costs quota) — run with:

    RUN_LIVE_TESTS=1 pytest tests/test_cache_metrics_live.py -v -s

Makes several calls with the SAME stable system prompt (prompts/answer_evaluator.md)
to see whether cached_tokens actually appears via OpenRouter -> underlying
provider. See ARCHITECTURE.md for the real measured result — this test is
how it was obtained, and can be re-run to re-measure after any prompt or
provider change.
"""
from __future__ import annotations

import pytest

from src.agents.cache_metrics import summarize
from src.agents.evaluator import evaluate_answer


@pytest.mark.live
def test_measure_evaluator_cache_behavior():
    answers = [
        "I used pdfplumber with a pypdf fallback for resume extraction.",
        "I chunked by paragraph with a 200 token overlap for the RAG index.",
        "I wrote unit tests with pytest and mocked the GPT calls.",
    ]
    for i, answer in enumerate(answers):
        evaluate_answer(
            question_text=f"Question {i}: tell me about a technical decision you made.",
            competency="backend",
            difficulty="medium",
            source_reference="",
            candidate_answer=answer,
            prior_turns=[],
        )
    summary = summarize()
    print("CACHE METRICS SUMMARY:", summary)
    assert summary["count"] >= 3
