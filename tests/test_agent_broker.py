from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from opencobalt.agent_broker.broker import (
    AgentBroker,
    BrokerExecution,
    ExecutionEngineCodexRunner,
)
from opencobalt.agent_broker.codex_adapter import CodexSdkBrokerAdapter
from opencobalt.agent_broker.store import AgentBrokerStore
from opencobalt.agent_broker.worker import _install_decline_handler


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.archives: list[dict] = []

    def run_turn(self, **kwargs):
        self.calls.append(kwargs)
        if not kwargs["execute"]:
            return BrokerExecution(status="planned", executed=False, receipt_id="receipt-plan")
        thread_id = kwargs["provider_session_id"] or "thr-test"
        return BrokerExecution(
            status="complete",
            executed=True,
            receipt_id=f"receipt-{len(self.calls)}",
            provider_session_id=thread_id,
            response=f"done:{kwargs['prompt']}",
            metadata={"cwd": kwargs["workspace_path"]},
        )

    def archive(self, **kwargs):
        self.archives.append(kwargs)
        return BrokerExecution(
            status="complete",
            executed=kwargs["execute"],
            receipt_id="receipt-archive",
            provider_session_id=kwargs["provider_session_id"],
        )


class FakeEngine:
    def __init__(self, outcome) -> None:
        self.outcome = outcome
        self.calls: list[dict] = []

    def run_task(self, task, **kwargs):
        self.calls.append({"task": task, **kwargs})
        return self.outcome


def workspace_factory(tmp_path: Path):
    authoritative = tmp_path / "repo"
    authoritative.mkdir()
    staging = tmp_path / "staging"
    staging.mkdir()

    def create(_repository: str):
        return {
            "workspace_id": "ws-test",
            "authoritative_path": str(authoritative),
            "staging_path": str(staging),
            "kind": "git_worktree",
            "branch": "feature/test",
            "head": "abc123",
            "baseline": {"branch": "feature/test", "head": "abc123"},
        }

    return create


def test_store_round_trip(tmp_path: Path) -> None:
    store = AgentBrokerStore(tmp_path / "ledger.db")
    runner = FakeRunner()
    broker = AgentBroker(
        store=store,
        runner=runner,
        db_path=tmp_path / "ledger.db",
        workspace_factory=workspace_factory(tmp_path),
    )

    session, execution = broker.start(
        repository="ignored",
        objective="inspect the repository",
        execute=True,
    )

    assert execution.status == "complete"
    assert session.status == "active"
    assert session.provider_session_id == "thr-test"
    assert session.last_receipt_id == "receipt-1"
    assert session.turn_count == 1
    assert session.source_branch == "feature/test"
    assert store.get_session(session.session_id) == session
    turns = store.list_turns(session.session_id)
    assert len(turns) == 1
    assert turns[0].receipt_id == "receipt-1"
    assert turns[0].provider_session_id == "thr-test"


def test_continue_resumes_same_provider_thread(tmp_path: Path) -> None:
    runner = FakeRunner()
    broker = AgentBroker(
        store=AgentBrokerStore(tmp_path / "ledger.db"),
        runner=runner,
        db_path=tmp_path / "ledger.db",
        workspace_factory=workspace_factory(tmp_path),
    )
    session, _ = broker.start(repository="ignored", objective="first", execute=True)
    continued, execution = broker.continue_session(session.session_id, "second", execute=True)

    assert execution.provider_session_id == "thr-test"
    assert continued.turn_count == 2
    assert runner.calls[1]["provider_session_id"] == "thr-test"
    assert runner.calls[1]["prompt"] == "second"
    assert [turn.sequence for turn in broker.turns(session.session_id)] == [1, 2]


def test_first_live_turn_replays_dry_run_context(tmp_path: Path) -> None:
    runner = FakeRunner()
    broker = AgentBroker(
        store=AgentBrokerStore(tmp_path / "ledger.db"),
        runner=runner,
        db_path=tmp_path / "ledger.db",
        workspace_factory=workspace_factory(tmp_path),
    )
    session, _ = broker.start(repository="ignored", objective="original objective")
    session, _ = broker.continue_session(session.session_id, "planned refinement")
    continued, execution = broker.continue_session(
        session.session_id,
        "implement now",
        execute=True,
    )

    provider_prompt = runner.calls[-1]["prompt"]
    assert runner.calls[-1]["provider_session_id"] is None
    assert "original objective" in provider_prompt
    assert "planned refinement" in provider_prompt
    assert provider_prompt.endswith("Current instruction:\nimplement now")
    assert execution.metadata["first_live_turn_replayed_planned_context"] is True
    assert continued.provider_session_id == "thr-test"
    assert broker.turns(session.session_id)[-1].prompt == "implement now"


def test_dry_run_records_plan_without_provider_thread(tmp_path: Path) -> None:
    broker = AgentBroker(
        store=AgentBrokerStore(tmp_path / "ledger.db"),
        runner=FakeRunner(),
        db_path=tmp_path / "ledger.db",
        workspace_factory=workspace_factory(tmp_path),
    )
    session, execution = broker.start(repository="ignored", objective="plan only")

    assert execution.executed is False
    assert session.status == "planned"
    assert session.provider_session_id is None
    assert session.last_receipt_id == "receipt-plan"


def test_requested_execution_block_is_failure_with_receipt(monkeypatch) -> None:
    monkeypatch.setattr(CodexSdkBrokerAdapter, "_sdk_available", staticmethod(lambda: True))
    outcome = SimpleNamespace(
        result=None,
        policy=SimpleNamespace(allowed=False, reason="explicit approval required"),
        receipt=SimpleNamespace(receipt_id="receipt-blocked", limitations=[]),
    )
    runner = ExecutionEngineCodexRunner(FakeEngine(outcome))

    result = runner.run_turn(
        prompt="push the branch",
        workspace_path="/tmp/staging",
        provider_session_id=None,
        model=None,
        execute=True,
        approved=False,
        timeout_seconds=30,
    )

    assert result.status == "failed"
    assert result.executed is False
    assert result.receipt_id == "receipt-blocked"
    assert "blocked by OpenCobalt policy" in (result.error or "")


def test_dry_run_without_result_remains_planned(monkeypatch) -> None:
    monkeypatch.setattr(CodexSdkBrokerAdapter, "_sdk_available", staticmethod(lambda: True))
    outcome = SimpleNamespace(
        result=None,
        policy=SimpleNamespace(allowed=True, reason="dry run"),
        receipt=SimpleNamespace(receipt_id="receipt-plan", limitations=[]),
    )
    runner = ExecutionEngineCodexRunner(FakeEngine(outcome))

    result = runner.run_turn(
        prompt="inspect tests",
        workspace_path="/tmp/staging",
        provider_session_id=None,
        model=None,
        execute=False,
        approved=False,
        timeout_seconds=30,
    )

    assert result.status == "planned"
    assert result.executed is False
    assert result.receipt_id == "receipt-plan"


def test_stop_blocks_future_continuation(tmp_path: Path) -> None:
    runner = FakeRunner()
    broker = AgentBroker(
        store=AgentBrokerStore(tmp_path / "ledger.db"),
        runner=runner,
        db_path=tmp_path / "ledger.db",
        workspace_factory=workspace_factory(tmp_path),
    )
    session, _ = broker.start(repository="ignored", objective="first", execute=True)
    stopped, archive = broker.stop(
        session.session_id,
        archive_provider=True,
        execute=True,
    )

    assert stopped.status == "stopped"
    assert archive is not None and archive.status == "complete"
    assert runner.archives[0]["provider_session_id"] == "thr-test"
    with pytest.raises(ValueError, match="stopped"):
        broker.continue_session(session.session_id, "more", execute=True)


def test_codex_adapter_builds_bounded_worker_command(monkeypatch) -> None:
    monkeypatch.setattr(CodexSdkBrokerAdapter, "_sdk_available", staticmethod(lambda: True))
    adapter = CodexSdkBrokerAdapter(
        provider_session_id="thr-123",
        model="gpt-test",
    )
    command = adapter.build_command("fix the tests")

    assert command[:3] == [command[0], "-m", "opencobalt.agent_broker.worker"]
    assert "--thread-id" in command
    assert command[command.index("--thread-id") + 1] == "thr-123"
    assert command[command.index("--model") + 1] == "gpt-test"
    assert command[-2:] == ["--prompt", "fix the tests"]
    assert not any("dangerously" in part for part in command)


def test_worker_installs_explicit_decline_handler() -> None:
    class Client:
        _approval_handler = None

    class Codex:
        _client = Client()

    codex = Codex()
    _install_decline_handler(codex)

    assert codex._client._approval_handler("item/commandExecution/requestApproval", {}) == {
        "decision": "decline"
    }
    assert codex._client._approval_handler("item/fileChange/requestApproval", {}) == {
        "decision": "decline"
    }
    assert codex._client._approval_handler("item/permissions/requestApproval", {}) == {
        "decision": "decline"
    }


def test_worker_fails_closed_if_sdk_handler_slot_changes() -> None:
    class Codex:
        _client = object()

    with pytest.raises(RuntimeError, match="approval boundary"):
        _install_decline_handler(Codex())
