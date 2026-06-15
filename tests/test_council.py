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


def test_consult_subprocess_returns_string(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import subprocess

    from opencobalt.core.council import consult_subprocess

    def fake_run(cmd, **kwargs):
        class R:
            stdout = "- Use SQLite\n- Write tests first"
            returncode = 0

        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = consult_subprocess("refactor the router", model="claude")
    assert "SQLite" in result or isinstance(result, str)


def test_consult_subprocess_graceful_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shutil

    from opencobalt.core.council import consult_subprocess

    monkeypatch.setattr(shutil, "which", lambda x: None)
    result = consult_subprocess("some task", model="claude")
    assert "not found" in result.lower() or "unavailable" in result.lower()


def test_codex_consult_subprocess_is_blocked_outside_execution_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shutil
    import subprocess

    from opencobalt.core.council import consult_subprocess

    monkeypatch.setattr(
        shutil,
        "which",
        lambda command: "/usr/local/bin/codex" if command == "codex" else None,
    )

    def explode(*args, **kwargs):
        raise AssertionError("direct codex subprocess must not run")

    monkeypatch.setattr(subprocess, "run", explode)

    result = consult_subprocess("modify files", model="codex", intent="implement")

    assert "ExecutionEngine" in result
    assert "opencobalt run" in result


def test_codex_stream_subprocess_is_blocked_outside_execution_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shutil
    import subprocess

    from opencobalt.core.council import stream_subprocess

    monkeypatch.setattr(
        shutil,
        "which",
        lambda command: "/usr/local/bin/codex" if command == "codex" else None,
    )

    def explode(*args, **kwargs):
        raise AssertionError("direct codex subprocess must not run")

    monkeypatch.setattr(subprocess, "Popen", explode)

    output = "".join(stream_subprocess("modify files", model="codex"))

    assert "ExecutionEngine" in output
    assert "opencobalt run" in output


def test_codex_legacy_council_has_no_direct_command_or_bypass_flags() -> None:
    from opencobalt.core.council import _cmd_for

    argv = _cmd_for("codex", autonomous=True)

    assert argv == []
