"""Cursor ACP provider, permission bridge, and coding-mission tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from opencobalt.core.approval_bridge import ApprovalStore
from opencobalt.core.mission_engine import MissionStore
from opencobalt.execution.adapters import CursorAdapter
from opencobalt.execution.engine import ExecutionEngine
from opencobalt.execution.runner import ProcessRunner
from opencobalt.execution.store import ExecutionStore
from opencobalt.personal_ai.coding import CodingMissionStore
from opencobalt.personal_ai.cursor_acp import (
    AcpClient,
    AcpPermissionGate,
    CursorACPProvider,
    parse_cursor_acp_payload,
    validate_repository_path,
)
from opencobalt.personal_ai.models import AISettings
from opencobalt.personal_ai.providers import CancellationToken, ProviderRequest
from opencobalt.personal_ai.router import PersonalAIRouter, ProviderSnapshot, RoutingRequest
from opencobalt.personal_ai.store import PersonalAIStore

ACP_HELP = """Usage: agent acp [options]

Start the Cursor Agent as an ACP (Agent Client Protocol) server
Transport: stdio JSON-RPC 2.0
"""


class ScriptedSession:
    def __init__(self, script: list[dict]) -> None:
        self.script = list(script)
        self.written: list[dict] = []
        self.cancelled = False
        self.alive = True

    def write_message(self, payload: dict) -> None:
        self.written.append(payload)

    def read_message(self, timeout: float | None = None) -> dict | None:
        _ = timeout
        if self.cancelled or not self.script:
            return None
        return self.script.pop(0)

    def remaining_seconds(self) -> float:
        return 30.0


def _acp_script(*, permission: dict | None = None, malformed: bool = False) -> list[dict]:
    script = [
        {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1, "authMethods": [{"id": "cursor_login"}]}},
        {"jsonrpc": "2.0", "id": 2, "result": {"ok": True}},
        {"jsonrpc": "2.0", "id": 3, "result": {"sessionId": "sess-acp-1"}},
    ]
    if malformed:
        script.append("not-json")  # type: ignore[arg-type]
        return script
    if permission is not None:
        script.append(
            {
                "jsonrpc": "2.0",
                "id": 99,
                "method": "session/request_permission",
                "params": permission,
            }
        )
    script.extend(
        [
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "hello from cursor"},
                    }
                },
            },
            {"jsonrpc": "2.0", "id": 4, "result": {"stopReason": "end_turn"}},
        ]
    )
    return script


def _read_permission() -> dict:
    return {
        "toolCall": {"toolCallId": "t1", "title": "Read router.py", "kind": "read"},
        "options": [
            {"optionId": "allow-once"},
            {"optionId": "allow-always"},
            {"optionId": "reject-once"},
        ],
    }


def _write_permission() -> dict:
    return {
        "toolCall": {"toolCallId": "t2", "title": "Edit router.py", "kind": "edit"},
        "options": [
            {"optionId": "allow-once"},
            {"optionId": "allow-always"},
            {"optionId": "reject-once"},
        ],
    }


def test_validate_repository_path_rejects_traversal_and_implicit_selection(tmp_path):
    with pytest.raises(ValueError, match="explicit repository path"):
        validate_repository_path(None)
    outside = tmp_path / ".." / "nope"
    with pytest.raises(ValueError):
        validate_repository_path(str(outside), workspace_root=tmp_path)
    nested = tmp_path / "repo"
    nested.mkdir()
    assert validate_repository_path(str(nested), workspace_root=tmp_path) == nested.resolve()


def test_acp_initialize_auth_session_and_streamed_update():
    session = ScriptedSession(_acp_script())
    client = AcpClient(session, cwd="/tmp/repo", mode="ask", prompt="explain this file")
    result = client.run_turn()
    methods = [item.get("method") for item in session.written if "method" in item]
    assert methods[:4] == ["initialize", "authenticate", "session/new", "session/prompt"]
    assert session.written[0]["params"]["protocolVersion"] == 1
    assert session.written[1]["params"]["methodId"] == "cursor_login"
    assert result["session_id"] == "sess-acp-1"
    assert result["content"] == "hello from cursor"
    assert result["status"] == "complete"


def test_session_load_is_skipped_unless_initialize_advertises_it():
    script = _acp_script()
    script[0]["result"]["agentCapabilities"] = {"loadSession": False}
    session = ScriptedSession(script)
    skipped = AcpClient(
        session, cwd="/tmp/repo", mode="ask", prompt="resume", resume_session_id="old-sess"
    ).run_turn()
    methods = [item.get("method") for item in session.written if "method" in item]
    assert "session/load" not in methods
    assert "session/new" in methods
    assert skipped["session_id"] == "sess-acp-1"

    load_script = _acp_script()
    load_script[0]["result"]["agentCapabilities"] = {"loadSession": True}
    load_script[2] = {
        "jsonrpc": "2.0",
        "id": 3,
        "result": {"sessionId": "old-sess"},
    }
    loaded_session = ScriptedSession(load_script)
    loaded = AcpClient(
        loaded_session,
        cwd="/tmp/repo",
        mode="ask",
        prompt="resume",
        resume_session_id="old-sess",
    ).run_turn()
    loaded_methods = [item.get("method") for item in loaded_session.written if "method" in item]
    assert loaded_methods[2] == "session/load"
    assert loaded["session_id"] == "old-sess"


def test_permission_allow_once_for_green_read_never_allow_always(tmp_path):
    store = ApprovalStore(tmp_path / "ledger.db")
    gate = AcpPermissionGate(mode="ask", bridge=__import__(
        "opencobalt.core.approval_bridge", fromlist=["ApprovalBridge"]
    ).ApprovalBridge(store=store))
    response = gate.decide(_read_permission())
    assert response["outcome"]["optionId"] == "allow-once"
    assert "allow-always" not in json.dumps(response)
    assert gate.records[0]["policy_decision"] == "auto_approved_green"


def test_permission_deny_for_write_in_analysis_mode_and_without_human(tmp_path):
    store = ApprovalStore(tmp_path / "ledger.db")
    from opencobalt.core.approval_bridge import ApprovalBridge

    analysis = AcpPermissionGate(mode="ask", bridge=ApprovalBridge(store=store))
    denied = analysis.decide(_write_permission())
    assert denied["outcome"]["optionId"] == "reject-once"
    agent = AcpPermissionGate(mode="agent", bridge=ApprovalBridge(store=store))
    pending = agent.decide(_write_permission())
    assert pending["outcome"]["optionId"] == "reject-once"
    assert agent.records[0]["policy_decision"] == "denied_missing_human"


def test_permission_human_allow_and_dangerous_auto_deny(tmp_path):
    from opencobalt.core.approval_bridge import ApprovalBridge

    store = ApprovalStore(tmp_path / "ledger.db")
    gate = AcpPermissionGate(
        mode="agent",
        bridge=ApprovalBridge(store=store),
        decision_hook=lambda _step: "approved",
    )
    allowed = gate.decide(_write_permission())
    assert allowed["outcome"]["optionId"] == "allow-once"
    dangerous = gate.decide(
        {
            "toolCall": {"title": "rm -rf / --force", "kind": "execute"},
            "options": [{"optionId": "allow-once"}, {"optionId": "allow-always"}, {"optionId": "reject-once"}],
        }
    )
    assert dangerous["outcome"]["optionId"] == "reject-once"
    assert gate.records[-1]["policy_decision"] == "denied_by_policy"


def test_acp_client_handles_permission_and_cancellation():
    session = ScriptedSession(_acp_script(permission=_read_permission()))
    client = AcpClient(session, cwd="/tmp/repo", mode="ask", prompt="read the file")
    result = client.run_turn()
    assert any(item.get("method") is None and item.get("result") for item in session.written)
    assert result["permissions"]
    token = CancellationToken()
    token.cancel()
    cancelled_session = ScriptedSession(_acp_script())
    cancelled = AcpClient(
        cancelled_session, cwd="/tmp/repo", mode="ask", prompt="hi", cancellation=token
    )
    outcome = cancelled.run_turn()
    assert outcome["status"] == "cancelled"


def test_malformed_acp_event_fails_safely():
    session = ScriptedSession(
        [
            {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": 1}},
            {"jsonrpc": "2.0", "id": 2, "result": {}},
            {"jsonrpc": "2.0", "id": 3, "result": {"sessionId": "s1"}},
            {"jsonrpc": "2.0", "id": 4, "result": "not-an-object"},
        ]
    )
    # Inject a non-dict line via read_message raising from InteractiveSession path:
    client = AcpClient(session, cwd="/tmp/repo", mode="ask", prompt="hi")
    result = client.run_turn()
    assert result["status"] in {"complete", "failed"}


def test_cursor_adapter_discovers_acp_without_unsafe_flags(tmp_path, monkeypatch):
    agent = tmp_path / "agent"
    agent.write_text("#!/bin/sh\nexit 0\n")
    agent.chmod(0o755)
    monkeypatch.setattr(
        "opencobalt.execution.adapters.shutil.which",
        lambda command: str(agent) if command in {"agent", "cursor-agent"} else None,
    )
    adapter = CursorAdapter(
        app_paths=(),
        help_text="",
        acp_help_text=ACP_HELP,
        about_text="User Email          user@example.com\n",
    )
    assert adapter.supports_acp() is True
    assert adapter.authentication_state() == "verified"
    argv = adapter.build_acp_command()
    assert argv == [str(agent), "acp"]
    assert "--force" not in argv
    assert "--yolo" not in argv
    assert "--api-key" not in argv


def test_cursor_unavailable_without_agent(monkeypatch):
    monkeypatch.setattr("opencobalt.execution.adapters.shutil.which", lambda command: None)
    adapter = CursorAdapter(app_paths=(), help_text="", acp_help_text="", about_text="")
    assert adapter.supports_acp() is False
    with pytest.raises(ValueError, match="ACP executable not found"):
        adapter.build_acp_command()


class _RecordingEngine:
    def __init__(self, session: ScriptedSession) -> None:
        self.session = session
        self.calls: list[dict] = []

    def run_task(self, task: str, **kwargs):
        self.calls.append({"task": task, **kwargs})
        handler = kwargs["session_handler"]
        payload = handler(self.session)
        stdout = json.dumps(payload)
        path = kwargs.get("cwd")
        stdout_path = Path(path) / "stdout.log" if path else None
        if stdout_path:
            stdout_path.write_text(stdout, encoding="utf-8")
        return SimpleNamespace(
            result=SimpleNamespace(
                status="succeeded",
                stdout_preview=stdout,
                stderr_preview="",
                error=None,
                usage=None,
                stdout_path=str(stdout_path) if stdout_path else None,
                content=stdout,
            ),
            receipt=SimpleNamespace(receipt_id="receipt-acp", limitations=[]),
            policy=SimpleNamespace(allowed=True, reason="allowed"),
        )


def test_cursor_provider_execute_and_local_only_and_missing_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    agent = tmp_path / "agent"
    agent.write_text("#!/bin/sh\nexit 0\n")
    agent.chmod(0o755)
    monkeypatch.setattr(
        "opencobalt.execution.adapters.shutil.which",
        lambda command: str(agent) if command == "agent" else None,
    )
    monkeypatch.chdir(tmp_path)
    adapter = CursorAdapter(
        app_paths=(),
        help_text="",
        acp_help_text=ACP_HELP,
        about_text="User Email          user@example.com\n",
    )
    engine = _RecordingEngine(ScriptedSession(_acp_script()))
    provider = CursorACPProvider(engine, adapter)
    blocked = provider.execute(
        ProviderRequest(message="explain router.py", local_only=True, cwd=str(repo))
    )
    assert blocked.status == "blocked"
    assert blocked.error.category == "local_only_violation"
    missing = provider.execute(ProviderRequest(message="explain router.py"))
    assert missing.status == "blocked"
    result = provider.execute(
        ProviderRequest(
            message="explain router.py",
            cwd=str(repo),
            metadata={"capability_role": "coding_analysis"},
        )
    )
    assert result.status == "complete"
    assert result.session_id == "sess-acp-1"
    assert "hello from cursor" in result.content
    chat_mutation = provider.execute(
        ProviderRequest(
            message="refactor router.py",
            cwd=str(repo),
            metadata={"capability_role": "coding_agent", "chat_surface": "general_chat"},
        )
    )
    assert chat_mutation.status == "blocked"
    mission_provider = CursorACPProvider(
        _RecordingEngine(ScriptedSession(_acp_script())), adapter
    )
    mission_ok = mission_provider.execute(
        ProviderRequest(
            message="refactor router.py",
            cwd=str(repo),
            metadata={"capability_role": "coding_agent", "chat_surface": "coding_mission"},
        )
    )
    assert mission_ok.status == "complete"


def test_cursor_provider_unavailable_when_acp_missing(monkeypatch):
    monkeypatch.setattr("opencobalt.execution.adapters.shutil.which", lambda command: None)
    adapter = CursorAdapter(app_paths=(), help_text="", acp_help_text="", about_text="")
    provider = CursorACPProvider(_RecordingEngine(ScriptedSession([])), adapter)
    result = provider.execute(ProviderRequest(message="explain code", cwd="/tmp"))
    assert result.status == "unavailable"


def test_process_runner_interact_jsonrpc_roundtrip(tmp_path):
    script = tmp_path / "fake_acp.py"
    script.write_text(
        "import json,sys\n"
        "line=sys.stdin.buffer.readline()\n"
        "msg=json.loads(line)\n"
        "if msg.get('method')=='initialize':\n"
        "    sys.stdout.buffer.write(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':{'protocolVersion':1}}).encode()+b'\\n')\n"
        "    sys.stdout.buffer.flush()\n"
    )
    runner = ProcessRunner(artifact_dir=tmp_path / "artifacts")

    def handler(session):
        session.write_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        reply = session.read_message(timeout=5)
        return {"status": "complete", "content": "ok", "reply": reply}

    result = runner.interact(
        [os.environ.get("PYTHON", "python3"), str(script)],
        plan_id="plan-1",
        handler=handler,
        timeout_seconds=10,
    )
    assert result.status == "succeeded"
    payload = json.loads(Path(result.stdout_path).read_text(encoding="utf-8"))
    assert payload["content"] == "ok"


def test_coding_mission_and_route_persistence(tmp_path):
    db = tmp_path / "ledger.db"
    store = PersonalAIStore(db)
    missions = MissionStore(db)
    coding = CodingMissionStore(store, missions)
    record = coding.create(
        objective="Refactor router.py and run tests",
        repository_path=str(tmp_path),
        conversation_id="conv-1",
        route_id="route-1",
        capability_role="coding_agent",
        provider_id="cursor",
        acp_session_id="sess-acp-1",
    )
    completed = coding.complete(
        record,
        status="complete",
        outcome="refactored",
        receipt_id="receipt-1",
        acp_session_id="sess-acp-1",
        model_id="cursor-acp",
        files_changed=["src/opencobalt/personal_ai/router.py"],
        terminal_operations=["pytest"],
        tests=["tests/test_personal_ai_router.py"],
        approvals=[{"option_id": "reject-once", "policy_decision": "denied_missing_human"}],
        limitations=[],
    )
    loaded = store.get_coding_mission(record["coding_id"])
    assert loaded["acp_session_id"] == "sess-acp-1"
    assert loaded["files_changed"] == ["src/opencobalt/personal_ai/router.py"]
    assert loaded["receipt_id"] == "receipt-1"
    assert missions.get_mission(record["mission_id"]).mission_type == "coding"
    assert completed["status"] == "complete"


def test_parse_cursor_acp_payload_and_malformed_json():
    parsed = parse_cursor_acp_payload('{"content":"hi","session_id":"s1"}')
    assert parsed["session_id"] == "s1"
    raw = parse_cursor_acp_payload("not json")
    assert raw["content"] == "not json"


def test_engine_interactive_cursor_acp_startup(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    script = tmp_path / "agent"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json,sys\n"
        "while True:\n"
        "    line=sys.stdin.buffer.readline()\n"
        "    if not line:\n"
        "        break\n"
        "    msg=json.loads(line)\n"
        "    method=msg.get('method')\n"
        "    if method=='initialize':\n"
        "        sys.stdout.buffer.write(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':{'protocolVersion':1}}).encode()+b'\\n')\n"
        "    elif method=='authenticate':\n"
        "        sys.stdout.buffer.write(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':{}}).encode()+b'\\n')\n"
        "    elif method=='session/new':\n"
        "        sys.stdout.buffer.write(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':{'sessionId':'live-sess'}}).encode()+b'\\n')\n"
        "    elif method=='session/prompt':\n"
        "        sys.stdout.buffer.write(json.dumps({'jsonrpc':'2.0','method':'session/update','params':{'update':{'sessionUpdate':'agent_message_chunk','content':{'text':'ok'}}}}).encode()+b'\\n')\n"
        "        sys.stdout.buffer.write(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':{'stopReason':'end_turn'}}).encode()+b'\\n')\n"
        "    sys.stdout.buffer.flush()\n"
    )
    script.chmod(0o755)
    monkeypatch.setattr(
        "opencobalt.execution.adapters.shutil.which",
        lambda command: str(script) if command == "agent" else None,
    )
    monkeypatch.chdir(tmp_path)
    adapter = CursorAdapter(
        app_paths=(),
        help_text="",
        acp_help_text=ACP_HELP,
        about_text="User Email          user@example.com\n",
    )
    engine = ExecutionEngine(
        store=ExecutionStore(tmp_path / "ledger.db"),
        runner=ProcessRunner(artifact_dir=tmp_path / "artifacts"),
        events_path=tmp_path / "execution.jsonl",
    )
    provider = CursorACPProvider(engine, adapter)
    result = provider.execute(
        ProviderRequest(
            message="Say hello",
            cwd=str(repo),
            timeout_seconds=20,
            metadata={"capability_role": "coding_analysis"},
        )
    )
    assert result.status == "complete", result.error
    assert result.session_id == "live-sess"
    assert "ok" in result.content
    assert result.receipt_id is not None


def test_routing_receipt_metadata_includes_capability_role():
    router = PersonalAIRouter()
    cursor = ProviderSnapshot(
        provider_id="cursor",
        model_id="cursor-acp",
        runtime_id="cursor",
        provider_family="cursor",
        available=True,
        local=False,
        requires_network=True,
        quality_tier="strong",
        capabilities=frozenset({"coding", "repository"}),
        capability_roles=frozenset({"coding_analysis", "coding_agent"}),
    )
    plan = router.route(
        RoutingRequest(
            request_id="req-1",
            conversation_id="conv-1",
            request_message_id="msg-1",
            prompt="Refactor router.py and run tests",
            requested_persona_id="analytical",
            project_path="/workspace/repo",
            settings=AISettings(),
        ),
        [cursor],
    )
    assert plan.capability_role == "coding_agent"
    assert plan.record.metadata["capability_role"] == "coding_agent"
    assert plan.record.selected_provider == "cursor"


@pytest.mark.skipif(
    os.environ.get("OPENCOBALT_LIVE_ACP") != "1",
    reason="live ACP smoke is opt-in via OPENCOBALT_LIVE_ACP=1",
)
def test_live_cursor_acp_initialize_smoke():
    from shutil import which

    agent = which("agent")
    if agent is None:
        pytest.skip("agent CLI is not installed")
    runner = ProcessRunner()

    def handler(session):
        session.write_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": False, "writeTextFile": False},
                        "terminal": False,
                    },
                    "clientInfo": {"name": "opencobalt-smoke", "version": "0.1.0"},
                },
            }
        )
        reply = session.read_message(timeout=20)
        session.close_stdin()
        return {"status": "complete", "initialize": reply}

    result = runner.interact(
        [agent, "acp"],
        plan_id="live-acp",
        handler=handler,
        timeout_seconds=25,
    )
    assert result.status in {"succeeded", "failed", "timeout"}
    payload = json.loads(Path(result.stdout_path).read_text(encoding="utf-8")) if result.stdout_path else {}
    assert payload.get("initialize") is not None or result.error
