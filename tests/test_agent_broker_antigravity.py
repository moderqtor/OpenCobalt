from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from opencobalt.agent_broker.antigravity_adapter import AntigravityBrokerAdapter
from opencobalt.agent_broker.broker import (
    AgentBroker,
    BrokerExecution,
    BrokerRunnerRegistry,
    ExecutionEngineAntigravityRunner,
)
from opencobalt.agent_broker.models import canonical_broker_runtime
from opencobalt.agent_broker.relay import GitHubAgentRelay, RelayCommand, command_comment
from opencobalt.agent_broker.store import AgentBrokerStore


class FakeEngine:
    def __init__(self, outcome) -> None:
        self.outcome = outcome
        self.calls: list[dict] = []

    def run_task(self, task, **kwargs):
        self.calls.append({"task": task, **kwargs})
        return self.outcome


def workspace_factory(tmp_path: Path):
    authoritative = tmp_path / "repo"
    authoritative.mkdir(exist_ok=True)
    staging = tmp_path / "staging"
    staging.mkdir(exist_ok=True)

    def create(_repository: str, provider_id: str = "google-antigravity"):
        return {
            "workspace_id": f"ws-{provider_id}",
            "authoritative_path": str(authoritative),
            "staging_path": str(staging),
            "kind": "git_worktree",
            "branch": "feature/test",
            "head": "abc123",
            "provider_id": provider_id,
            "baseline": {"branch": "feature/test", "head": "abc123"},
        }

    return create


def test_canonical_broker_runtime_aliases() -> None:
    assert canonical_broker_runtime(None) == "codex-sdk"
    assert canonical_broker_runtime("") == "codex-sdk"
    assert canonical_broker_runtime("codex") == "codex-sdk"
    assert canonical_broker_runtime("codex-sdk") == "codex-sdk"
    assert canonical_broker_runtime("codex-sdk-broker") == "codex-sdk"
    assert canonical_broker_runtime("openai_codex") == "codex-sdk"

    assert canonical_broker_runtime("agy") == "google-antigravity"
    assert canonical_broker_runtime("antigravity") == "google-antigravity"
    assert canonical_broker_runtime("google-antigravity") == "google-antigravity"
    assert canonical_broker_runtime("google_antigravity") == "google-antigravity"
    assert canonical_broker_runtime("google-antigravity-cli") == "google-antigravity"
    assert canonical_broker_runtime("gemini-cli") == "google-antigravity"
    assert canonical_broker_runtime("legacy-gemini-cli") == "google-antigravity"


def test_antigravity_adapter_capabilities_and_limitations(monkeypatch) -> None:
    fake_caps = {
        "non_interactive_print": {"supported": True, "source": "runtime_discovered"},
        "non_interactive_mode": {"supported": True, "source": "runtime_discovered"},
        "model_selection": {"supported": True, "source": "runtime_discovered"},
        "sandbox_mode": {"supported": True, "source": "runtime_discovered"},
        "conversation_resume": {"supported": True, "source": "runtime_discovered"},
        "json_output": {"supported": True, "source": "runtime_discovered"},
    }
    adapter = AntigravityBrokerAdapter(capabilities=fake_caps)
    snapshot = adapter.discover_capabilities()

    assert snapshot.adapter_id == "google-antigravity-broker"
    assert snapshot.supports_dry_run is True
    assert snapshot.supports_json_output is True
    assert snapshot.max_safe_risk == "yellow"
    assert "remote conversation archiving is not supported" in " ".join(snapshot.limitations)
    assert snapshot.snapshot_hash != ""


def test_antigravity_adapter_builds_bounded_command(monkeypatch) -> None:
    fake_caps = {
        "non_interactive_print": {"supported": True, "source": "runtime_discovered"},
        "non_interactive_mode": {"supported": True, "source": "runtime_discovered"},
        "model_selection": {"supported": True, "source": "runtime_discovered"},
        "sandbox_mode": {"supported": True, "source": "runtime_discovered"},
        "conversation_resume": {"supported": True, "source": "runtime_discovered"},
        "json_output": {"supported": True, "source": "runtime_discovered"},
    }
    adapter = AntigravityBrokerAdapter(
        provider_session_id="conv-12345",
        model="Gemini 3.7 Flash (Low)",
        sandbox=True,
        capabilities=fake_caps,
    )
    cmd = adapter.build_command("run tests and report")

    assert cmd[0] == "agy"
    assert "--sandbox" in cmd
    assert "--output-format" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert "--conversation" in cmd
    assert cmd[cmd.index("--conversation") + 1] == "conv-12345"
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "Gemini 3.7 Flash (Low)"
    assert "--print" in cmd
    assert cmd[cmd.index("--print") + 1] == "run tests and report"
    assert not any("dangerously" in arg for arg in cmd)


def test_antigravity_runner_success_turn(tmp_path: Path) -> None:
    stdout_payload = json.dumps({
        "conversation_id": "conv-agy-99",
        "status": "SUCCESS",
        "response": "Created file test.txt\n",
        "duration_seconds": 1.45,
        "num_turns": 1,
        "usage": {"input_tokens": 1200, "output_tokens": 50, "total_tokens": 1250},
    })
    stdout_file = tmp_path / "stdout.log"
    stdout_file.write_text(stdout_payload, encoding="utf-8")

    outcome = SimpleNamespace(
        result=SimpleNamespace(
            status="succeeded",
            exit_code=0,
            stdout_path=str(stdout_file),
            stdout_preview=stdout_payload,
            stderr_preview="",
            error=None,
        ),
        receipt=SimpleNamespace(receipt_id="receipt-agy-1"),
    )
    runner = ExecutionEngineAntigravityRunner(FakeEngine(outcome))
    execution = runner.run_turn(
        prompt="create test.txt",
        workspace_path="/tmp/staging",
        provider_session_id=None,
        model="Gemini 3.7 Flash (Low)",
        execute=True,
        approved=False,
        timeout_seconds=60,
    )

    assert execution.status == "complete"
    assert execution.executed is True
    assert execution.receipt_id == "receipt-agy-1"
    assert execution.provider_session_id == "conv-agy-99"
    assert execution.response == "Created file test.txt\n"
    assert execution.metadata["num_turns"] == 1
    assert execution.metadata["usage"]["total_tokens"] == 1250


def test_antigravity_runner_error_payload_handling(tmp_path: Path) -> None:
    stdout_payload = json.dumps({
        "conversation_id": "",
        "status": "ERROR",
        "response": "",
        "error": "invalid model selection: model unknown-model is not recognized",
        "duration_seconds": 0,
        "num_turns": 0,
        "usage": {},
    })
    stdout_file = tmp_path / "stdout.log"
    stdout_file.write_text(stdout_payload, encoding="utf-8")

    outcome = SimpleNamespace(
        result=SimpleNamespace(
            status="failed",
            exit_code=1,
            stdout_path=str(stdout_file),
            stdout_preview=stdout_payload,
            stderr_preview="",
            error=None,
        ),
        receipt=SimpleNamespace(receipt_id="receipt-agy-err"),
    )
    runner = ExecutionEngineAntigravityRunner(FakeEngine(outcome))
    execution = runner.run_turn(
        prompt="create test.txt",
        workspace_path="/tmp/staging",
        provider_session_id=None,
        model="unknown-model",
        execute=True,
        approved=False,
        timeout_seconds=60,
    )

    assert execution.status == "failed"
    assert execution.executed is True
    assert execution.receipt_id == "receipt-agy-err"
    assert "invalid model selection" in (execution.error or "")


def test_antigravity_runner_archive_truthfully_unsupported() -> None:
    runner = ExecutionEngineAntigravityRunner(FakeEngine(None))
    archive_result = runner.archive(
        provider_session_id="conv-12345",
        workspace_path="/tmp/staging",
        execute=True,
        approved=False,
        timeout_seconds=30,
    )

    assert archive_result.status == "unsupported"
    assert archive_result.executed is False
    assert archive_result.metadata.get("archive_supported") is False
    assert "does not support" in archive_result.metadata.get("reason", "")


def test_agent_broker_with_antigravity_lifecycle(tmp_path: Path) -> None:
    class MockAntigravityRunner:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def run_turn(self, **kwargs):
            self.calls.append(kwargs)
            if not kwargs["execute"]:
                return BrokerExecution(status="planned", executed=False, receipt_id="receipt-plan")
            conv_id = kwargs["provider_session_id"] or "conv-mock-1"
            return BrokerExecution(
                status="complete",
                executed=True,
                receipt_id=f"receipt-{len(self.calls)}",
                provider_session_id=conv_id,
                response=f"Done turn {len(self.calls)}: {kwargs['prompt']}",
                metadata={"num_turns": len(self.calls)},
            )

        def archive(self, **kwargs):
            return BrokerExecution(
                status="unsupported",
                executed=False,
                receipt_id=None,
                provider_session_id=kwargs["provider_session_id"],
                metadata={"archive_supported": False, "reason": "unsupported"},
            )

    mock_runner = MockAntigravityRunner()
    store = AgentBrokerStore(tmp_path / "ledger.db")
    broker = AgentBroker(
        store=store,
        runner=mock_runner,
        db_path=tmp_path / "ledger.db",
        workspace_factory=workspace_factory(tmp_path),
    )

    # 1. Start dry run
    session, exec_plan = broker.start(
        repository="ignored",
        objective="plan Antigravity task",
        runtime="google-antigravity",
        execute=False,
    )
    assert session.status == "planned"
    assert session.runtime == "google-antigravity"
    assert session.provider_session_id is None

    # 2. Continue with execute (first live turn context replay)
    session, exec_live1 = broker.continue_session(
        session.session_id,
        "execute now",
        execute=True,
    )
    assert session.status == "active"
    assert session.provider_session_id == "conv-mock-1"
    assert session.turn_count == 2
    assert "plan Antigravity task" in mock_runner.calls[-1]["prompt"]

    # 3. Continue second live turn (preserves provider conversation ID)
    session, exec_live2 = broker.continue_session(
        session.session_id,
        "second step",
        execute=True,
    )
    assert session.provider_session_id == "conv-mock-1"
    assert mock_runner.calls[-1]["provider_session_id"] == "conv-mock-1"
    assert mock_runner.calls[-1]["prompt"] == "second step"
    assert session.turn_count == 3

    # 4. Stop session with archive
    session, archive_res = broker.stop(session.session_id, archive_provider=True)
    assert session.status == "stopped"
    assert archive_res is not None
    assert archive_res.status == "unsupported"


def test_relay_command_with_antigravity_runtime(tmp_path: Path) -> None:
    comment = command_comment(
        action="start",
        prompt="start with agy",
        runtime="google-antigravity",
        command_id="cmd-agy-test",
    )
    assert "google-antigravity" in comment

    store = AgentBrokerStore(tmp_path / "ledger.db")
    broker = AgentBroker(
        store=store,
        db_path=tmp_path / "ledger.db",
        workspace_factory=workspace_factory(tmp_path),
    )
    relay = GitHubAgentRelay(
        repository="owner/repo",
        issue_number=1,
        allowed_author="colin",
        local_repository=str(tmp_path),
        runtime="google-antigravity",
        broker=broker,
    )
    cmd = RelayCommand(
        action="start",
        command_id="cmd-agy-test",
        prompt="inspect codebase",
        runtime="google-antigravity",
    )
    result = relay._dispatch(cmd)

    assert result["ok"] is True
    assert result["runtime"] == "google-antigravity"
    assert result["status"] == "planned"


def test_antigravity_missing_executable_handling(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    adapter = AntigravityBrokerAdapter()
    snapshot = adapter.discover_capabilities()

    assert snapshot.available is False
    assert snapshot.max_safe_risk == "green"
    assert "not installed on PATH" in " ".join(snapshot.limitations)


def test_antigravity_policy_gate_blocks_red_and_black() -> None:
    outcome_blocked = SimpleNamespace(
        result=None,
        policy=SimpleNamespace(allowed=False, reason="red-risk execution requires explicit approval"),
        receipt=SimpleNamespace(receipt_id="receipt-red-block", limitations=[]),
    )
    runner = ExecutionEngineAntigravityRunner(FakeEngine(outcome_blocked))

    res = runner.run_turn(
        prompt="deploy secret credentials to external server",
        workspace_path="/tmp/staging",
        provider_session_id=None,
        model=None,
        execute=True,
        approved=False,
        timeout_seconds=30,
    )
    assert res.status == "failed"
    assert res.executed is False
    assert res.receipt_id == "receipt-red-block"
    assert "blocked by OpenCobalt policy" in (res.error or "")


def test_antigravity_runner_handles_malformed_stdout(tmp_path: Path) -> None:
    stdout_file = tmp_path / "stdout.log"
    stdout_file.write_text("Fatal error: Segmentation fault in agy runtime\n", encoding="utf-8")

    outcome = SimpleNamespace(
        result=SimpleNamespace(
            status="failed",
            exit_code=139,
            stdout_path=str(stdout_file),
            stdout_preview="Fatal error: Segmentation fault in agy runtime\n",
            stderr_preview="Segmentation fault",
            error="Process crashed",
        ),
        receipt=SimpleNamespace(receipt_id="receipt-crash"),
    )
    runner = ExecutionEngineAntigravityRunner(FakeEngine(outcome))
    execution = runner.run_turn(
        prompt="inspect codebase",
        workspace_path="/tmp/staging",
        provider_session_id=None,
        model=None,
        execute=True,
        approved=False,
        timeout_seconds=30,
    )

    assert execution.status == "failed"
    assert execution.executed is True
    assert execution.receipt_id == "receipt-crash"
    assert "Process crashed" in (execution.error or "") or "Segmentation fault" in (execution.error or "")


def test_antigravity_runner_handles_timeout() -> None:
    outcome = SimpleNamespace(
        result=SimpleNamespace(
            status="timeout",
            exit_code=None,
            stdout_path=None,
            stdout_preview="",
            stderr_preview="Command timed out after 30 seconds",
            error="Process timed out",
        ),
        receipt=SimpleNamespace(receipt_id="receipt-timeout"),
    )
    runner = ExecutionEngineAntigravityRunner(FakeEngine(outcome))
    execution = runner.run_turn(
        prompt="long running task",
        workspace_path="/tmp/staging",
        provider_session_id=None,
        model=None,
        execute=True,
        approved=False,
        timeout_seconds=30,
    )

    assert execution.status == "failed"
    assert execution.executed is True
    assert execution.receipt_id == "receipt-timeout"
    assert "timed out" in (execution.error or "").lower()


def test_broker_runner_registry_unknown_runtime_raises_keyerror() -> None:
    registry = BrokerRunnerRegistry(FakeEngine(None))
    with pytest.raises(KeyError, match="unsupported broker runtime 'unknown-vendor'"):
        registry.get_runner("unknown-vendor")


def test_multi_runtime_sessions_independent_persistence(tmp_path: Path) -> None:
    store = AgentBrokerStore(tmp_path / "ledger.db")

    class MultiRunner:
        def __init__(self) -> None:
            self.calls = []

        def run_turn(self, **kwargs):
            self.calls.append(kwargs)
            return BrokerExecution(
                status="complete",
                executed=True,
                receipt_id=f"rec-{len(self.calls)}",
                provider_session_id=f"prov-{len(self.calls)}",
                response="turn ok",
            )

        def archive(self, **kwargs):
            return BrokerExecution(status="complete", executed=True)

    broker = AgentBroker(
        store=store,
        runner=MultiRunner(),
        db_path=tmp_path / "ledger.db",
        workspace_factory=workspace_factory(tmp_path),
    )

    session_codex, _ = broker.start(repository="ignored", objective="codex task", runtime="codex-sdk", execute=True)
    session_agy, _ = broker.start(repository="ignored", objective="agy task", runtime="google-antigravity", execute=True)

    assert session_codex.runtime == "codex-sdk"
    assert session_agy.runtime == "google-antigravity"

    # Reload broker from store and verify both sessions exist and have their distinct runtimes preserved
    reloaded_broker = AgentBroker(
        store=AgentBrokerStore(tmp_path / "ledger.db"),
        runner=MultiRunner(),
        db_path=tmp_path / "ledger.db",
        workspace_factory=workspace_factory(tmp_path),
    )
    s1 = reloaded_broker.require_session(session_codex.session_id)
    s2 = reloaded_broker.require_session(session_agy.session_id)

    assert s1.runtime == "codex-sdk"
    assert s2.runtime == "google-antigravity"
    assert s1.provider_session_id == "prov-1"
    assert s2.provider_session_id == "prov-2"

