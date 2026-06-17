"""Regression tests for the external runtime execution boundary."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("model", "runtime"),
    [
        ("claude", "claude-code"),
        ("claude-code", "claude-code"),
        ("codex", "codex-cli"),
        ("codex-cli", "codex-cli"),
        ("cursor", "cursor"),
        ("antigravity", "google-antigravity"),
        ("google-antigravity", "google-antigravity"),
        ("gemini", "google-antigravity"),
        ("gemini-cli", "google-antigravity"),
        ("agy", "google-antigravity"),
        ("ollama", "ollama"),
        ("aider", "aider"),
    ],
)
def test_legacy_council_consult_blocks_direct_runtime_subprocesses(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    runtime: str,
) -> None:
    import shutil

    from opencobalt.core.council import consult_subprocess

    monkeypatch.setattr(shutil, "which", lambda command: f"/usr/local/bin/{command}")

    def explode(*args, **kwargs):
        raise AssertionError(f"direct {model} subprocess must not run")

    monkeypatch.setattr(subprocess, "run", explode)

    result = consult_subprocess("modify files", model=model, intent="implement")

    assert result.startswith("[blocked]")
    assert "ExecutionEngine" in result
    assert f"--runtime {runtime}" in result
    assert "opencobalt run" in result


@pytest.mark.parametrize(
    ("model", "runtime"),
    [
        ("claude", "claude-code"),
        ("cursor", "cursor"),
        ("antigravity", "google-antigravity"),
        ("gemini", "google-antigravity"),
        ("ollama", "ollama"),
        ("aider", "aider"),
    ],
)
def test_legacy_council_stream_blocks_direct_runtime_subprocesses(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    runtime: str,
) -> None:
    import shutil

    from opencobalt.core.council import stream_subprocess

    monkeypatch.setattr(shutil, "which", lambda command: f"/usr/local/bin/{command}")

    def explode(*args, **kwargs):
        raise AssertionError(f"direct {model} subprocess must not run")

    monkeypatch.setattr(subprocess, "Popen", explode)

    output = "".join(stream_subprocess("modify files", model=model))

    assert output.startswith("[blocked]")
    assert "ExecutionEngine" in output
    assert f"--runtime {runtime}" in output
    assert "opencobalt run" in output


def test_council_session_blocks_explicit_external_models() -> None:
    from opencobalt.core.council import CouncilSession

    result = CouncilSession().consult(
        "review this change",
        models=["claude", "gemini", "ollama"],
    )

    assert set(result.responses) == {"claude", "gemini", "ollama"}
    assert all("ExecutionEngine" in response for response in result.responses.values())


@pytest.mark.parametrize(
    "tool",
    [
        "claude",
        "claude-code",
        "codex",
        "codex-cli",
        "cursor",
        "antigravity",
        "google-antigravity",
        "agy",
        "gemini",
        "gemini-cli",
        "ollama",
        "aider",
    ],
)
def test_legacy_pipeline_blocks_external_runtime_steps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tool: str,
) -> None:
    import shutil

    from opencobalt.core.pipeline import Pipeline, PipelineStep

    monkeypatch.setattr(shutil, "which", lambda command: f"/usr/local/bin/{command}")

    def explode(*args, **kwargs):
        raise AssertionError(f"direct {tool} pipeline subprocess must not run")

    monkeypatch.setattr(subprocess, "run", explode)

    pipeline = Pipeline(output_dir=tmp_path / "pipelines")
    out_path = pipeline._step_output_path("run-1", 0)

    ok = pipeline._run_step(PipelineStep(tool=tool), "Task: modify files", out_path)

    assert ok is False
    output = out_path.read_text(encoding="utf-8")
    assert output.startswith("[blocked]")
    assert "ExecutionEngine" in output
    assert "opencobalt run" in output


def test_route_exec_blocks_legacy_launcher_without_popen(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import shutil

    from opencobalt.cli import _route_exec

    monkeypatch.setattr("opencobalt.cli._clipboard_brief", lambda *args, **kwargs: None)
    monkeypatch.setattr(shutil, "which", lambda command: f"/usr/local/bin/{command}")

    def explode(*args, **kwargs):
        raise AssertionError("route --exec must not launch external runtimes directly")

    monkeypatch.setattr(subprocess, "Popen", explode)

    _route_exec("claude-code", "modify files", dry_run=False)

    output = capsys.readouterr().out
    assert "[blocked]" in output
    assert "ExecutionEngine" in output
    assert "--runtime claude-code" in output
    assert "opencobalt run" in output


def test_shell_open_tool_blocks_external_runtime_without_popen(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import shutil

    from opencobalt.shell import CobaltShell

    shell = CobaltShell(
        db_path=tmp_path / "ledger.db",
        bridge_path=tmp_path / "memories.db",
    )
    monkeypatch.setattr(shutil, "which", lambda command: f"/usr/local/bin/{command}")

    def explode(*args, **kwargs):
        raise AssertionError("shell must not launch external runtimes directly")

    monkeypatch.setattr(subprocess, "Popen", explode)

    shell._open_tool("claude-code", "modify files")

    output = capsys.readouterr().out
    assert "[blocked]" in output
    assert "ExecutionEngine" in output
    assert "--runtime claude-code" in output


@pytest.mark.parametrize(
    "agent_name",
    [
        "summarizer",
        "tagger",
    ],
)
def test_legacy_ollama_agents_block_direct_task_execution(
    monkeypatch: pytest.MonkeyPatch,
    agent_name: str,
) -> None:
    from opencobalt.agents.registry import get_agent

    def explode(*args, **kwargs):
        raise AssertionError("legacy Ollama agents must not call ollama run directly")

    monkeypatch.setattr(subprocess, "run", explode)

    agent = get_agent(agent_name)
    assert agent is not None

    result = agent.run("summarize or tag this task")

    assert result.startswith("[blocked]")
    assert "ExecutionEngine" in result
    assert "--runtime ollama" in result


def test_orchestration_blocked_runtime_output_is_not_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opencobalt.core.models import SubTask
    from opencobalt.core.orchestrator import OrchestrationExecutor

    monkeypatch.setattr(
        "opencobalt.core.orchestrator.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )

    def explode(*args, **kwargs):
        raise AssertionError("orchestrator must not start external runtimes directly")

    monkeypatch.setattr(subprocess, "Popen", explode)
    monkeypatch.setattr(subprocess, "run", explode)

    subtask = SubTask(task_type="impl", prompt="modify files", preferred_tool="claude-code")
    result = OrchestrationExecutor().run("modify files", [subtask], show_live=False)

    assert result.success is False
    assert result.outputs[subtask.id].startswith("[blocked]")
    assert "ExecutionEngine" in result.outputs[subtask.id]


def test_autonomous_task_blocked_runtime_output_is_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opencobalt.core.autonomous_runner import AutonomousRunner, AutonomousTask

    def explode(*args, **kwargs):
        raise AssertionError("autonomous runner must not start external runtimes directly")

    monkeypatch.setattr(subprocess, "Popen", explode)
    monkeypatch.setattr(subprocess, "run", explode)

    task = AutonomousTask(
        id="task-1",
        task="modify files",
        tool="claude-code",
        task_type="impl",
    )

    AutonomousRunner()._execute_task(task)

    assert task.status == "failed"
    assert task.output.startswith("[blocked]")
    assert "ExecutionEngine" in task.output


def test_ollama_judge_falls_back_without_direct_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opencobalt.core.ollama_judge import OllamaJudge

    def explode(*args, **kwargs):
        raise AssertionError("OllamaJudge must not call ollama directly")

    monkeypatch.setattr(subprocess, "run", explode)

    result = OllamaJudge().judge(prompt="score this", output="answer", heuristics={})

    assert result["_judge"] == "heuristic"


def test_auto_committer_never_runs_git_push_when_flag_is_set(tmp_path: Path) -> None:
    from opencobalt.core.auto_committer import AutoCommitter

    (tmp_path / "f.py").write_text("x")
    calls: list[list[str]] = []

    def run_git(args, cwd):
        calls.append(args)
        if args == ["git", "push"]:
            raise AssertionError("AutoCommitter must not push directly")
        if args == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="abc12345\n", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    committer = AutoCommitter(repo_path=tmp_path, run_git=run_git, push_on_converge=True)
    result = committer.commit(
        session_id="s",
        seed_task="t",
        artifact_paths=["f.py"],
        artifact_lines=[],
        waves=1,
        retries=0,
        agents=[],
        tests_info="n/a",
        verifier_info="n/a",
    )

    assert ["git", "push"] not in calls
    assert result.pushed is False
