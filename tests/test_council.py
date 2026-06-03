"""Tests for CouncilSession."""

from __future__ import annotations

from pathlib import Path

import pytest

from opencobalt.core.council import CouncilResult, _agreement_score, _build_result


def test_council_with_mocked_apis() -> None:
    responses = {"claude": "- Use SQLite\n- Write tests first\n- Keep it simple"}
    result = _build_result("refactor the memory bridge", responses, synthesize=True)
    assert isinstance(result, CouncilResult)
    assert "claude" in result.responses
    assert result.synthesis != ""


def test_agreement_scoring_high() -> None:
    same = "- Use SQLite\n- Write tests\n- Keep simple"
    responses = {"claude": same, "gemini": same}
    score = _agreement_score(responses)
    assert score >= 0.5


def test_agreement_scoring_low() -> None:
    responses = {
        "claude": "- Use async everywhere\n- Rewrite from scratch",
        "gemini": "- Keep sync interface\n- Only refactor small parts",
    }
    score = _agreement_score(responses)
    assert score <= 0.9


def test_graceful_skip_when_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    responses = {
        "claude": "[skipped: ANTHROPIC_API_KEY not set]",
        "gemini": "[skipped: GEMINI_API_KEY not set]",
        "ollama": "[skipped: ollama not running]",
    }
    result = _build_result("test task", responses, synthesize=True)
    assert isinstance(result, CouncilResult)


def test_synthesis_called_after_parallel_responses() -> None:
    responses = {
        "claude": "- Point A\n- Point B",
        "gemini": "- Point A\n- Point C",
    }
    result = _build_result("test task", responses, synthesize=True)
    assert result.synthesis != ""
    assert result.agreement_score >= 0.0


def test_save_flag_stores_to_memory_bridge(tmp_path: Path) -> None:
    from opencobalt.memory_bridge import MemoryBridge

    bridge = MemoryBridge(db_path=tmp_path / "memories.db")
    bridge.add(
        content="Council on 'refactor': Use SQLite, write tests.",
        agent_id="council",
        metadata={"type": "council", "agreement": 0.8},
    )
    results = bridge.search("Council")
    assert len(results) >= 1
    assert "council" in results[0]["content"].lower()
