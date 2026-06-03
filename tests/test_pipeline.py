"""Tests for Pipeline executor."""

from __future__ import annotations

from pathlib import Path

import pytest

from opencobalt.core.pipeline import Pipeline


def test_parse_simple_pipeline():
    p = Pipeline(output_dir=Path("/tmp/test-pipe"))
    task, steps = p.parse('/pipe "add rate limiting" → claude → codex → /verify')
    assert task == "add rate limiting"
    assert len(steps) == 3
    assert steps[0].tool == "claude"
    assert steps[1].tool == "codex"
    assert steps[2].tool == "verify"


def test_parse_with_hints():
    p = Pipeline(output_dir=Path("/tmp/test-pipe"))
    _task, steps = p.parse('/pipe "build auth" → claude design → codex implement → /verify')
    assert steps[0].tool == "claude"
    assert steps[0].hint == "design"
    assert steps[1].tool == "codex"
    assert steps[1].hint == "implement"


def test_parse_rejects_empty():
    p = Pipeline(output_dir=Path("/tmp/test-pipe"))
    with pytest.raises(ValueError, match="No steps"):
        p.parse('/pipe "task"')


def test_parse_note_step():
    p = Pipeline(output_dir=Path("/tmp/test-pipe"))
    _task, steps = p.parse('/pipe "task" → claude → /note checkpoint reached → /verify')
    assert steps[1].tool == "note"
    assert "checkpoint" in steps[1].hint


def test_step_output_path(tmp_path):
    p = Pipeline(output_dir=tmp_path / "pipelines")
    path = p._step_output_path("run-1", 0)
    assert path.parent.exists() or not path.exists()
    assert "step-0" in str(path)
