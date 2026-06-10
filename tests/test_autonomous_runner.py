"""Tests for the autonomous long-running execution engine."""

from __future__ import annotations

from unittest.mock import patch

from opencobalt.core.autonomous_runner import AutonomousRunner, AutonomousTask


def test_autonomous_task_elapsed_before_start():
    t = AutonomousTask(
        id="t1", task="build it", tool="claude-code",
        task_type="impl",
    )
    assert t.elapsed == 0.0
    assert t.status == "queued"


def test_available_tools_returns_list(tmp_path):
    runner = AutonomousRunner(log_dir=tmp_path / "logs")
    tools = runner._available_tools()
    assert isinstance(tools, list)
    # Each tool is a known key
    for t in tools:
        assert t in ("claude-code", "codex-cli", "google-antigravity", "ollama")


def test_classify_task_impl():
    runner = AutonomousRunner()
    assert runner._classify_task("implement a login page") == "impl"
    assert runner._classify_task("write unit tests for auth") == "tests"
    assert runner._classify_task("document the API") == "docs"
    assert runner._classify_task("security review the codebase") == "review"
    assert runner._classify_task("analyze the performance") == "analyze"
    assert runner._classify_task("summarize the session") == "summarize"


def test_rotate_tool_cycles(tmp_path):
    runner = AutonomousRunner(log_dir=tmp_path / "logs")
    available = ["claude-code", "codex-cli"]
    first = runner._rotate_tool(available)
    second = runner._rotate_tool(available)
    assert first in available
    assert second in available
    # Should alternate between available tools
    assert first != second or len(available) == 1


def test_run_with_no_tools_returns_early(tmp_path):
    runner = AutonomousRunner(max_iterations=2, log_dir=tmp_path / "logs")
    with patch.object(runner, "_available_tools", return_value=[]):
        session = runner.run("build something")
    assert session.seed_task == "build something"
    assert len(session.tasks) == 0


def test_run_single_iteration(tmp_path):
    runner = AutonomousRunner(max_iterations=1, log_dir=tmp_path / "logs")

    def fake_execute(task):
        task.status = "done"
        task.output = "implemented successfully"
        import time
        task.started_at = time.monotonic() - 1
        task.finished_at = time.monotonic()

    with patch.object(runner, "_available_tools", return_value=["claude-code"]):
        with patch.object(runner, "_execute_task", side_effect=fake_execute):
            with patch.object(runner, "_generate_followups", return_value=[]):
                session = runner.run("implement auth")

    assert session.seed_task == "implement auth"
    assert session.iterations >= 1


def test_log_creates_file(tmp_path):
    runner = AutonomousRunner(log_dir=tmp_path / "logs")

    with patch.object(runner, "_available_tools", return_value=[]):
        runner.run("seed task")

    # Log file should be created
    logs = list((tmp_path / "logs").glob("auto_*.md"))
    assert len(logs) == 1
    content = logs[0].read_text()
    assert "seed task" in content


def test_fmt_elapsed():
    runner = AutonomousRunner()
    assert runner._fmt_elapsed(0) == "0s"
    assert runner._fmt_elapsed(45) == "45s"
    assert runner._fmt_elapsed(90) == "1:30"
    assert runner._fmt_elapsed(3661) == "1h01m"
