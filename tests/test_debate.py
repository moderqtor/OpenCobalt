"""Tests for DebateSession (mocked APIs)."""

from __future__ import annotations

from unittest.mock import patch

from opencobalt.core.debate import DebateResult, DebateSession, _extract_verdict


def _patch_query(for_resp: str, against_resp: str, judge_resp: str):
    """Context manager that patches _query_model with fixed responses."""
    call_count = [0]
    responses = [for_resp, against_resp, judge_resp]

    async def fake_query(task: str, model: str) -> str:
        idx = min(call_count[0], len(responses) - 1)
        call_count[0] += 1
        return responses[idx]

    return patch("opencobalt.core.debate._query_model", side_effect=fake_query)


def test_debate_runs_with_mocked_models() -> None:
    with _patch_query(
        for_resp="- Semantic routing catches edge cases\n- Better long-term",
        against_resp="- Keyword scoring is debuggable\n- No hallucination risk",
        judge_resp="Against wins. Debuggability matters at this stage.",
    ):
        session = DebateSession()
        result = session.run("should router use embeddings?", for_model="claude", against_model="gemini", judge_model="ollama")

    assert isinstance(result, DebateResult)
    assert result.for_model == "claude"
    assert result.against_model == "gemini"
    assert result.judge_model == "ollama"
    assert "Semantic" in result.for_argument
    assert "Keyword" in result.against_argument


def test_extract_verdict_for_wins() -> None:
    judgment = "The for side wins because semantic routing is more robust. My recommendation is to add embeddings."
    winner, rec = _extract_verdict(judgment)
    assert winner == "FOR"
    assert len(rec) > 0


def test_extract_verdict_against_wins() -> None:
    judgment = "Against wins. Keyword scoring is more debuggable and predictable."
    winner, rec = _extract_verdict(judgment)
    assert winner == "AGAINST"


def test_extract_verdict_unclear() -> None:
    judgment = "Both sides make valid points."
    winner, rec = _extract_verdict(judgment)
    assert winner == "unclear"


def test_debate_graceful_with_unavailable_models() -> None:
    async def always_skip(task: str, model: str) -> str:
        return "[skipped: model unavailable]"

    with patch("opencobalt.core.debate._query_model", side_effect=always_skip):
        session = DebateSession()
        result = session.run("test question", for_model="claude", against_model="gemini", judge_model="ollama")

    assert isinstance(result, DebateResult)
    assert "skipped" in result.for_argument.lower()
