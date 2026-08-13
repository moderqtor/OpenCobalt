"""Live approval lifecycle for ACP and future provider runtimes."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from opencobalt.api_server import app
from opencobalt.core.approval_bridge import ApprovalBridge, ApprovalStore, BlockedStepError
from opencobalt.core.approval_runtime import LiveApprovalCoordinator, redact_arguments
from opencobalt.personal_ai.cursor_acp import (
    AcpClient,
    AcpPermissionGate,
    CursorACPProvider,
    changed_paths,
    classify_permission_risk,
    path_escapes_repository,
    snapshot_repository,
    validate_repository_path,
)
from opencobalt.personal_ai.providers import CancellationToken, ProviderRequest
from tests.test_cursor_acp import (
    ACP_HELP,
    ScriptedSession,
    _acp_script,
    _read_permission,
    _write_permission,
)


def _coordinator(tmp_path: Path) -> LiveApprovalCoordinator:
    store = ApprovalStore(tmp_path / "ledger.db")
    return LiveApprovalCoordinator(ApprovalBridge(store=store), wait_seconds=2)


def _write_with_path(path: str) -> dict:
    payload = _write_permission()
    payload["toolCall"]["locations"] = [{"path": path}]
    payload["toolCall"]["rawInput"] = {"path": path, "api_key": "sk-secret-value"}
    return payload


def test_pending_approval_persists(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    gate = AcpPermissionGate(
        mode="agent",
        bridge=coordinator.bridge,
        coordinator=coordinator,
        wait_seconds=2,
    )
    result: dict = {}

    def run() -> None:
        result["response"] = gate.decide(_write_permission())

    worker = threading.Thread(target=run)
    worker.start()
    request_id = _wait_for_pending(coordinator)
    stored = coordinator.bridge.store.get_request(request_id)
    assert stored is not None
    assert stored.state == "pending"
    assert stored.steps[0].approval_state == "pending"
    coordinator.decide(request_id, decision="rejected")
    worker.join(timeout=3)
    assert result["response"]["outcome"]["optionId"] == "reject-once"


def test_allow_once_and_deny_transitions(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    allowed = _run_gate_decision(coordinator, _write_permission(), "approved")
    assert allowed["outcome"]["optionId"] == "allow-once"
    denied = _run_gate_decision(coordinator, _write_permission(), "rejected")
    assert denied["outcome"]["optionId"] == "reject-once"


def test_duplicate_decision_rejected(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    gate = AcpPermissionGate(
        mode="agent", bridge=coordinator.bridge, coordinator=coordinator, wait_seconds=2
    )
    worker = threading.Thread(target=lambda: gate.decide(_write_permission()))
    worker.start()
    request_id = _wait_for_pending(coordinator)
    coordinator.decide(request_id, decision="approved")
    worker.join(timeout=3)
    try:
        coordinator.decide(request_id, decision="approved")
        raise AssertionError("duplicate decision should fail")
    except Exception as exc:
        assert "pending" in str(exc).lower() or "stale" in str(exc).lower() or "not waiting" in str(exc).lower()


def test_stale_approval_rejected_after_restart(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    gate = AcpPermissionGate(
        mode="agent", bridge=coordinator.bridge, coordinator=coordinator, wait_seconds=2
    )
    worker = threading.Thread(target=lambda: gate.decide(_write_permission()))
    worker.start()
    request_id = _wait_for_pending(coordinator)
    restarted = LiveApprovalCoordinator(coordinator.bridge, wait_seconds=2)
    assert restarted.mark_orphaned_acp_stale() >= 1
    stored = restarted.bridge.store.get_request(request_id)
    assert stored is not None
    assert stored.state == "stale"
    try:
        restarted.decide(request_id, decision="approved")
        raise AssertionError("stale approval should not be actionable")
    except Exception as exc:
        assert "stale" in str(exc).lower() or "not waiting" in str(exc).lower()
    coordinator.cancel_execution(
        str(coordinator.bridge.store.get_request(request_id).metadata.get("execution_id") or "")
    )
    with coordinator._lock:
        waiter = next(iter(coordinator._waiters.values()), None)
    if waiter is not None:
        waiter.decision = "stale"
        waiter.event.set()
    worker.join(timeout=3)


def test_cancellation_while_waiting(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    token = CancellationToken()
    gate = AcpPermissionGate(
        mode="agent", bridge=coordinator.bridge, coordinator=coordinator, wait_seconds=5
    )
    result: dict = {}

    def run() -> None:
        result["response"] = gate.decide(_write_permission(), cancelled=lambda: token.cancelled)

    worker = threading.Thread(target=run)
    worker.start()
    request_id = _wait_for_pending(coordinator)
    token.cancel()
    coordinator.cancel_execution("missing")
    worker.join(timeout=3)
    assert result["response"]["outcome"]["optionId"] == "reject-once"
    stored = coordinator.bridge.store.get_request(request_id)
    assert stored is not None
    assert stored.state in {"stale", "rejected"}


def test_provider_failure_while_waiting(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    alive = {"value": True}
    gate = AcpPermissionGate(
        mode="agent", bridge=coordinator.bridge, coordinator=coordinator, wait_seconds=5
    )
    result: dict = {}

    def run() -> None:
        result["response"] = gate.decide(_write_permission(), is_alive=lambda: alive["value"])

    worker = threading.Thread(target=run)
    worker.start()
    request_id = _wait_for_pending(coordinator)
    alive["value"] = False
    worker.join(timeout=3)
    stored = coordinator.bridge.store.get_request(request_id)
    assert stored is not None
    assert stored.state == "stale"
    assert result["response"]["outcome"]["optionId"] == "reject-once"


def test_analysis_mode_write_denied(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    gate = AcpPermissionGate(mode="ask", bridge=coordinator.bridge, coordinator=coordinator)
    denied = gate.decide(_write_permission())
    assert denied["outcome"]["optionId"] == "reject-once"
    assert gate.records[0]["policy_decision"] == "denied_by_policy"
    assert coordinator.list_public(state="pending") == []


def test_hard_deny_cannot_be_human_overridden(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    gate = AcpPermissionGate(mode="agent", bridge=coordinator.bridge, coordinator=coordinator)
    dangerous = gate.decide(
        {
            "toolCall": {"title": "rm -rf / --force", "kind": "execute"},
            "options": [{"optionId": "allow-once"}, {"optionId": "reject-once"}],
        }
    )
    assert dangerous["outcome"]["optionId"] == "reject-once"
    request_id = gate.records[-1]["approval_request_id"]
    try:
        coordinator.decide(request_id, decision="approved", require_live=False)
        raise AssertionError("black-risk allow should fail")
    except (BlockedStepError, Exception) as exc:
        assert "black" in str(exc).lower() or "pending" in str(exc).lower() or "stale" in str(exc).lower()


def test_path_escape_is_hard_denied(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    coordinator = _coordinator(tmp_path)
    gate = AcpPermissionGate(
        mode="agent",
        bridge=coordinator.bridge,
        coordinator=coordinator,
        repository=repo,
    )
    denied = gate.decide(_write_with_path(str(tmp_path / "other" / "secret.py")))
    assert denied["outcome"]["optionId"] == "reject-once"
    assert gate.records[0]["policy_decision"] == "denied_by_policy"
    assert path_escapes_repository("../secret.py", repo) is True


def test_mutation_title_is_not_auto_approved_as_read() -> None:
    risk, _summary = classify_permission_risk(
        {
            "toolCall": {"title": "Edit app.py", "kind": "read"},
            "options": [{"optionId": "allow-once"}, {"optionId": "reject-once"}],
        },
        mode="agent",
    )
    assert risk != "green"


def test_redaction_of_sensitive_arguments() -> None:
    redacted = redact_arguments({"path": "router.py", "api_key": "sk-secret", "token": "abc"})
    assert redacted["path"] == "router.py"
    assert redacted["api_key"] == "<redacted>"
    assert redacted["token"] == "<redacted>"


def test_acp_permission_response_encoding_and_continuation(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    session = ScriptedSession(_acp_script(permission=_write_permission()))
    gate = AcpPermissionGate(
        mode="agent", bridge=coordinator.bridge, coordinator=coordinator, wait_seconds=3
    )
    result: dict = {}

    def run() -> None:
        result["turn"] = AcpClient(
            session, cwd=str(tmp_path), mode="agent", prompt="edit", permission_gate=gate
        ).run_turn()

    worker = threading.Thread(target=run)
    worker.start()
    request_id = _wait_for_pending(coordinator)
    coordinator.decide(request_id, decision="approved")
    worker.join(timeout=5)
    turn = result["turn"]
    assert turn["status"] == "complete"
    assert turn["content"] == "hello from cursor"
    assert any(
        item.get("id") == 99 and item.get("result", {}).get("outcome", {}).get("optionId") == "allow-once"
        for item in session.written
    )


def test_acp_deny_does_not_allow_mutation(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    session = ScriptedSession(_acp_script(permission=_write_permission()))
    gate = AcpPermissionGate(
        mode="agent", bridge=coordinator.bridge, coordinator=coordinator, wait_seconds=3
    )
    result: dict = {}

    def run() -> None:
        result["turn"] = AcpClient(
            session, cwd=str(tmp_path), mode="agent", prompt="edit", permission_gate=gate
        ).run_turn()

    worker = threading.Thread(target=run)
    worker.start()
    request_id = _wait_for_pending(coordinator)
    coordinator.decide(request_id, decision="rejected")
    worker.join(timeout=5)
    assert any(
        item.get("id") == 99 and item.get("result", {}).get("outcome", {}).get("optionId") == "reject-once"
        for item in session.written
    )
    stored = coordinator.bridge.store.get_request(request_id)
    assert stored is not None
    assert stored.state == "rejected"


def test_local_only_still_excludes_cursor(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(tmp_path)
    from opencobalt.execution.adapters import CursorAdapter

    adapter = CursorAdapter(
        app_paths=(),
        help_text="",
        acp_help_text=ACP_HELP,
        about_text="User Email          user@example.com\n",
    )
    provider = CursorACPProvider(SimpleNamespace(), adapter)
    blocked = provider.execute(
        ProviderRequest(message="explain router.py", local_only=True, cwd=str(repo))
    )
    assert blocked.status == "blocked"
    assert blocked.error.category == "local_only_violation"


def test_general_chat_cannot_gain_coding_agent_authority(tmp_path, monkeypatch) -> None:
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
    from opencobalt.execution.adapters import CursorAdapter

    adapter = CursorAdapter(
        app_paths=(),
        help_text="",
        acp_help_text=ACP_HELP,
        about_text="User Email          user@example.com\n",
    )
    provider = CursorACPProvider(SimpleNamespace(run_task=lambda *a, **k: None), adapter)
    blocked = provider.execute(
        ProviderRequest(
            message="refactor router.py",
            cwd=str(repo),
            metadata={"capability_role": "coding_agent", "chat_surface": "general_chat"},
        )
    )
    assert blocked.status == "blocked"


def test_validate_repository_allows_explicit_external_repo(tmp_path: Path) -> None:
    repo = tmp_path / "external"
    repo.mkdir()
    assert validate_repository_path(str(repo)) == repo.resolve()
    assert classify_permission_risk(_read_permission(), mode="ask")[0] == "green"


def test_api_allow_once_deny_and_stale(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with TestClient(app) as client:
        from opencobalt.personal_ai.api import _api_context

        context = _api_context()
        gate = AcpPermissionGate(
            mode="agent",
            bridge=context.approvals.bridge,
            coordinator=context.approvals,
            wait_seconds=4,
        )
        from opencobalt.core.approval_runtime import LiveApprovalContext

        gate.context = LiveApprovalContext(
            execution_id="chatx-live",
            mission_id="mis-1",
            route_id="route-1",
            conversation_id="conv-1",
            capability_role="coding_agent",
            repository_path=str(tmp_path),
            provider="cursor",
            runtime="cursor",
        )
        worker = threading.Thread(target=lambda: gate.decide(_write_permission()))
        worker.start()
        request_id = None
        for _ in range(80):
            pending = client.get("/api/v1/approvals", params={"state": "pending"}).json()
            if pending:
                request_id = pending[0]["request_id"]
                break
            time.sleep(0.05)
        assert request_id
        listed = client.get("/api/v1/approvals", params={"execution_id": "chatx-live"}).json()
        assert listed[0]["request_id"] == request_id
        inspected = client.get(f"/api/v1/approvals/{request_id}").json()
        assert inspected["state"] == "pending"
        assert inspected["actionable"] is True
        allowed = client.post(f"/api/v1/approvals/{request_id}/allow-once", json={"reason": "safe write"})
        assert allowed.status_code == 200
        body = allowed.json()
        assert body["decision"] == "allow_once"
        assert body["new_state"] == "approved"
        worker.join(timeout=3)
        duplicate = client.post(f"/api/v1/approvals/{request_id}/allow-once")
        assert duplicate.status_code == 409
        missing = client.post("/api/v1/approvals/areq-missing/deny")
        assert missing.status_code == 404

        gate2 = AcpPermissionGate(
            mode="agent",
            bridge=context.approvals.bridge,
            coordinator=context.approvals,
            context=gate.context,
            wait_seconds=4,
        )
        worker2 = threading.Thread(target=lambda: gate2.decide(_write_permission()))
        worker2.start()
        deny_id = None
        for _ in range(80):
            pending = client.get("/api/v1/approvals", params={"state": "pending"}).json()
            if pending:
                deny_id = pending[0]["request_id"]
                break
            time.sleep(0.05)
        denied = client.post(f"/api/v1/approvals/{deny_id}/deny")
        assert denied.status_code == 200
        assert denied.json()["decision"] == "deny"
        worker2.join(timeout=3)


def test_mission_and_route_linkage_in_approval_metadata(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    from opencobalt.core.approval_runtime import LiveApprovalContext

    gate = AcpPermissionGate(
        mode="agent",
        bridge=coordinator.bridge,
        coordinator=coordinator,
        context=LiveApprovalContext(
            execution_id="chatx-1",
            mission_id="mis-1",
            route_id="route-1",
            conversation_id="conv-1",
            provider="cursor",
            capability_role="coding_agent",
            repository_path=str(tmp_path),
        ),
        wait_seconds=2,
    )
    worker = threading.Thread(target=lambda: gate.decide(_write_permission()))
    worker.start()
    request_id = _wait_for_pending(coordinator)
    view = coordinator.list_public(mission_id="mis-1")[0]
    assert view["execution_id"] == "chatx-1"
    assert view["route_id"] == "route-1"
    assert view["capability_role"] == "coding_agent"
    coordinator.decide(request_id, decision="approved")
    worker.join(timeout=3)


def _wait_for_pending(coordinator: LiveApprovalCoordinator) -> str:
    for _ in range(80):
        pending = coordinator.list_public(state="pending")
        if pending:
            return pending[0]["request_id"]
        time.sleep(0.05)
    raise AssertionError("pending approval did not appear")


def _run_gate_decision(coordinator: LiveApprovalCoordinator, params: dict, decision: str) -> dict:
    gate = AcpPermissionGate(
        mode="agent", bridge=coordinator.bridge, coordinator=coordinator, wait_seconds=2
    )
    result: dict = {}

    def run() -> None:
        result["response"] = gate.decide(params)

    worker = threading.Thread(target=run)
    worker.start()
    request_id = _wait_for_pending(coordinator)
    coordinator.decide(request_id, decision=decision)  # type: ignore[arg-type]
    worker.join(timeout=3)
    return result["response"]


def test_repository_snapshot_detects_unsolicited_mutation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    before = snapshot_repository(repo)
    (repo / "app.py").write_text("def value():\n    return 99\n", encoding="utf-8")
    after = snapshot_repository(repo)
    assert changed_paths(before, after) == ["app.py"]
