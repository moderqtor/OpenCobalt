"""Opt-in live Cursor ACP coding vertical slice. Run with OPENCOBALT_LIVE_ACP=1."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from opencobalt.core.approval_bridge import ApprovalBridge, ApprovalStore
from opencobalt.core.approval_runtime import LiveApprovalCoordinator
from opencobalt.core.mission_engine import MissionStore
from opencobalt.execution.adapters import CursorAdapter
from opencobalt.execution.engine import ExecutionEngine
from opencobalt.execution.runner import ProcessRunner
from opencobalt.execution.store import ExecutionStore
from opencobalt.personal_ai.coding import CodingMissionStore
from opencobalt.personal_ai.cursor_acp import CursorACPProvider
from opencobalt.personal_ai.providers import ProviderRequest
from opencobalt.personal_ai.store import PersonalAIStore

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENCOBALT_LIVE_ACP") != "1",
    reason="live ACP smoke is opt-in via OPENCOBALT_LIVE_ACP=1",
)


def _live_stack(tmp_path: Path):
    db = tmp_path / "ledger.db"
    store = ApprovalStore(db)
    personal = PersonalAIStore(db)
    coordinator = LiveApprovalCoordinator(ApprovalBridge(store=store), wait_seconds=180)
    engine = ExecutionEngine(
        store=ExecutionStore(db),
        runner=ProcessRunner(artifact_dir=tmp_path / "artifacts"),
        events_path=tmp_path / "execution.jsonl",
    )
    provider = CursorACPProvider(
        engine,
        CursorAdapter(),
        approval_store=store,
        coordinator=coordinator,
        store=personal,
        staging_root=tmp_path / "staging",
    )
    return coordinator, engine, provider, personal, MissionStore(db)


def _allow_pending(coordinator: LiveApprovalCoordinator, *, deny: bool = False) -> None:
    deadline = time.monotonic() + 170
    while time.monotonic() < deadline:
        for item in coordinator.list_public(state="pending"):
            if not item.get("actionable"):
                continue
            if item.get("risk_level") == "black":
                continue
            coordinator.decide(
                item["request_id"],
                decision="rejected" if deny else "approved",
                reason="live smoke",
            )
        time.sleep(0.4)


def test_live_coding_analysis_does_not_require_write_approval(tmp_path: Path):
    repo = tmp_path / "analysis-repo"
    repo.mkdir()
    (repo / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    coordinator, _engine, provider, _store, _missions = _live_stack(tmp_path)
    result = provider.execute(
        ProviderRequest(
            message=(
                "Explain the structure of this repository and identify the file "
                "containing the main behavior. Do not modify anything."
            ),
            cwd=str(repo),
            timeout_seconds=180,
            metadata={
                "capability_role": "coding_analysis",
                "chat_surface": "coding_mission",
            },
        )
    )
    assert result.status == "complete", result.error
    assert result.receipt_id
    writes = [
        item
        for item in result.metadata.get("acp_permissions", [])
        if isinstance(item, dict)
        and item.get("option_id") == "allow-once"
        and item.get("risk_level") != "green"
    ]
    assert writes == []
    assert "app.py" in result.content or "value" in result.content
    assert coordinator.list_public(state="pending") == []


def test_live_coding_agent_allow_once_mutates_disposable_repo(tmp_path: Path):
    source = os.environ.get("OPENCOBALT_LIVE_REPO")
    repo = Path(source) if source else tmp_path / "agent-repo"
    if not source:
        repo.mkdir()
        (repo / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
        (repo / "test_app.py").write_text(
            "from app import value\n\ndef test_value():\n    assert value() == 1\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
    original = (repo / "app.py").read_text(encoding="utf-8")
    coordinator, engine, provider, store, missions = _live_stack(tmp_path)
    coding = CodingMissionStore(store, missions).create(
        objective="Add a function that returns 42 and add a passing test.",
        repository_path=str(repo),
        conversation_id="conv-live",
        route_id="route-live",
        capability_role="coding_agent",
        provider_id="cursor",
    )
    threading.Thread(target=_allow_pending, args=(coordinator,), daemon=True).start()
    result = provider.execute(
        ProviderRequest(
            message=(
                "Add a function named answer that returns 42 in app.py and add a "
                "passing test. Do not change unrelated files."
            ),
            cwd=str(repo),
            timeout_seconds=300,
            metadata={
                "capability_role": "coding_agent",
                "chat_surface": "coding_mission",
                "execution_id": "chatx-live-agent",
                "mission_id": coding["mission_id"],
                "coding_mission_id": coding["coding_id"],
                "route_id": "route-live",
            },
        )
    )
    assert result.status in {"complete", "failed", "cancelled"}, result.error
    assert (repo / "app.py").read_text(encoding="utf-8") == original
    changeset = result.metadata.get("changeset") or {}
    assert changeset.get("changeset_id"), result.metadata
    assert changeset.get("promotion_state") in {"pending", "empty", "blocked"}
    if changeset.get("promotion_state") == "pending":
        from opencobalt.personal_ai.staging import StagingController

        controller = StagingController(
            store,
            staging_root=tmp_path / "staging",
            approval_store=coordinator.bridge.store,
        )
        applied = controller.apply_changeset(changeset["changeset_id"])
        assert applied.promotion_state == "applied"
        assert "42" in (repo / "app.py").read_text(encoding="utf-8")
    assert result.receipt_id
    receipt = engine.store.get_receipt(result.receipt_id)
    assert receipt is not None


def test_live_coding_agent_deny_does_not_apply_forbidden_write(tmp_path: Path):
    repo = tmp_path / "deny-repo"
    repo.mkdir()
    original = "def value():\n    return 1\n"
    (repo / "app.py").write_text(original, encoding="utf-8")
    coordinator, _engine, provider, _store, _missions = _live_stack(tmp_path)
    threading.Thread(
        target=_allow_pending, args=(coordinator,), kwargs={"deny": True}, daemon=True
    ).start()
    result = provider.execute(
        ProviderRequest(
            message="Replace app.py with a function that returns 99.",
            cwd=str(repo),
            timeout_seconds=180,
            metadata={
                "capability_role": "coding_agent",
                "chat_surface": "coding_mission",
                "execution_id": "chatx-live-deny",
            },
        )
    )
    permissions = result.metadata.get("acp_permissions") or []
    denied = [item for item in permissions if item.get("option_id") == "reject-once"]
    changed = (repo / "app.py").read_text(encoding="utf-8") != original
    unsolicited = any(
        "without an ACP permission request" in item for item in result.limitations
    )
    if changed:
        assert unsolicited or denied, {
            "status": result.status,
            "permissions": permissions,
            "limitations": result.limitations,
        }
    assert denied or unsolicited or result.status in {"failed", "cancelled", "complete"}
