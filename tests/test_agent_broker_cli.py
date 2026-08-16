import json
from pathlib import Path

from typer.testing import CliRunner

from opencobalt.agent_broker.broker import BrokerExecution
from opencobalt.agent_broker.cli import app
from opencobalt.agent_broker.models import AgentBrokerSession

runner = CliRunner()


def test_cli_command_generator() -> None:
    result = runner.invoke(app, ["command", "start", "--prompt", "inspect repo", "-r", "google-antigravity"])
    assert result.exit_code == 0
    assert "<!-- opencobalt-agent-command:v1 -->" in result.output
    assert "google-antigravity" in result.output


def test_cli_start_and_status_and_stop(tmp_path: Path, monkeypatch) -> None:
    session_fake = AgentBrokerSession(
        session_id="agent-cli-test",
        runtime="google-antigravity",
        provider_session_id="conv-cli-123",
        objective="test CLI flow",
        repository_path=str(tmp_path),
        workspace_id="ws-cli",
        workspace_path=str(tmp_path / "staging"),
        source_branch="main",
        starting_head="abc",
        status="active",
        turn_count=1,
    )
    exec_fake = BrokerExecution(
        status="complete",
        executed=True,
        receipt_id="rec-cli-1",
        provider_session_id="conv-cli-123",
        response="cli turn complete",
    )

    class MockBroker:
        def start(self, **kwargs):
            return session_fake, exec_fake

        def continue_session(self, session_id: str, prompt: str, **kwargs):
            return session_fake.model_copy(update={"turn_count": 2}), exec_fake

        def require_session(self, session_id: str):
            return session_fake

        def list_sessions(self, limit: int = 20):
            return [session_fake]

        def turns(self, session_id: str):
            return []

        def stop(self, session_id: str, **kwargs):
            return session_fake.model_copy(update={"status": "stopped"}), exec_fake

    monkeypatch.setattr("opencobalt.agent_broker.cli.AgentBroker", MockBroker)

    # 1. start
    res_start = runner.invoke(
        app,
        ["start", "test CLI flow", "--repo", str(tmp_path), "-r", "google-antigravity", "--execute", "--json"],
    )
    assert res_start.exit_code == 0
    data_start = json.loads(res_start.output)
    assert data_start["session_id"] == "agent-cli-test"
    assert data_start["runtime"] == "google-antigravity"
    assert data_start["execution"]["status"] == "complete"

    # 2. continue
    res_cont = runner.invoke(app, ["continue", "agent-cli-test", "next step", "--execute", "--json"])
    assert res_cont.exit_code == 0
    data_cont = json.loads(res_cont.output)
    assert data_cont["turn_count"] == 2

    # 3. status single session
    res_stat = runner.invoke(app, ["status", "agent-cli-test", "--json"])
    assert res_stat.exit_code == 0
    data_stat = json.loads(res_stat.output)
    assert data_stat["session_id"] == "agent-cli-test"
    assert "turns" in data_stat

    # 4. status all sessions
    res_stat_all = runner.invoke(app, ["status", "--json"])
    assert res_stat_all.exit_code == 0
    data_stat_all = json.loads(res_stat_all.output)
    assert len(data_stat_all) == 1

    # 5. stop
    res_stop = runner.invoke(app, ["stop", "agent-cli-test", "--json"])
    assert res_stop.exit_code == 0
    data_stop = json.loads(res_stop.output)
    assert data_stop["status"] == "stopped"


def test_worker_main_turn_and_archive(monkeypatch, capsys) -> None:
    from opencobalt.agent_broker import worker

    # Mock _turn to return structured dict
    monkeypatch.setattr(worker, "_turn", lambda prompt, thread_id, model: {"ok": True, "thread_id": "thr-worker-1", "response": "ok"})
    monkeypatch.setattr(worker, "_archive", lambda thread_id: {"ok": True, "thread_id": "thr-worker-1"})

    # Test turn
    monkeypatch.setattr("sys.argv", ["worker.py", "turn", "--prompt", "inspect code"])
    worker.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["thread_id"] == "thr-worker-1"

    # Test archive
    monkeypatch.setattr("sys.argv", ["worker.py", "archive", "--thread-id", "thr-worker-1"])
    worker.main()
    captured_arch = capsys.readouterr()
    payload_arch = json.loads(captured_arch.out)
    assert payload_arch["ok"] is True
    assert payload_arch["thread_id"] == "thr-worker-1"
