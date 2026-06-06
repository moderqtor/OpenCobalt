import pytest
from unittest.mock import patch
from opencobalt.core.orchestrator import (
    OrchestrationDSLParser,
    OrchestrationExecutor,
    OrchestrationSession,
    ResultSynthesizer,
)
from opencobalt.core.models import SubTask, OrchestrationResult


def _make_subtask(task_type: str, tool: str) -> SubTask:
    return SubTask(
        task_type=task_type,
        prompt=f"do the {task_type}",
        preferred_tool=tool,
    )


def test_synthesizer_merges_outputs():
    st1 = _make_subtask("impl", "claude-code")
    st2 = _make_subtask("tests", "codex-cli")
    outputs = {st1.id: "impl output", st2.id: "test output"}
    subtasks = [st1, st2]
    s = ResultSynthesizer()
    result = s.synthesize("build auth", subtasks, outputs)
    assert "impl output" in result
    assert "test output" in result
    assert "impl" in result


def test_synthesizer_empty_outputs():
    s = ResultSynthesizer()
    result = s.synthesize("build auth", [], {})
    assert isinstance(result, str)


def test_executor_runs_subtasks():
    st1 = _make_subtask("impl", "claude-code")
    st2 = _make_subtask("tests", "codex-cli")

    def fake_dispatch(subtask):
        return f"output for {subtask.task_type}"

    executor = OrchestrationExecutor()
    with patch.object(executor, "_dispatch_subtask", side_effect=fake_dispatch):
        result = executor.run("build auth", [st1, st2])

    assert result.success
    assert len(result.outputs) == 2
    assert result.elapsed_s >= 0


def test_executor_handles_missing_tool():
    st = _make_subtask("impl", "nonexistent-tool-xyz")
    executor = OrchestrationExecutor()
    result = executor.run("build auth", [st])
    output = result.outputs.get(st.id, "")
    assert output.startswith("[")


def test_executor_partial_failure_still_succeeds():
    st_good = _make_subtask("summarize", "ollama")
    st_bad = _make_subtask("impl", "nonexistent-xyz")

    call_count = {"n": 0}

    def fake_dispatch(subtask):
        call_count["n"] += 1
        if subtask.preferred_tool == "nonexistent-xyz":
            return "[nonexistent-xyz not available]"
        return "summarized output"

    executor = OrchestrationExecutor()
    with patch.object(executor, "_dispatch_subtask", side_effect=fake_dispatch):
        result = executor.run("do stuff", [st_good, st_bad])

    assert result.success
    assert call_count["n"] == 2


# --- DSL parser tests ---

def test_dsl_parser_auto_mode():
    p = OrchestrationDSLParser()
    task, explicit_agents = p.parse("implement OAuth2 with tests")
    assert task == "implement OAuth2 with tests"
    assert explicit_agents == []


def test_dsl_parser_explicit_agents():
    p = OrchestrationDSLParser()
    task, explicit_agents = p.parse(
        '"implement auth" -> [claude:impl, codex:tests] -> merge'
    )
    assert task == "implement auth"
    assert "claude" in explicit_agents
    assert "codex" in explicit_agents


def test_dsl_parser_quoted_task_no_stages():
    p = OrchestrationDSLParser()
    task, explicit_agents = p.parse('"just this task"')
    assert task == "just this task"
    assert explicit_agents == []


def test_session_run_auto():
    session = OrchestrationSession()
    with patch.object(
        session._executor, "_dispatch_subtask", return_value="fake output"
    ):
        result = session.run("implement OAuth2 with tests")

    assert result.success
    assert result.synthesis


def test_session_run_explicit():
    session = OrchestrationSession()
    with patch.object(
        session._executor, "_dispatch_subtask", return_value="fake output"
    ):
        result = session.run('"implement auth" -> [claude:impl, codex:tests] -> merge')

    assert result.task == "implement auth"
    assert result.success
