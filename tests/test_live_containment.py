"""Opt-in live Cursor ACP containment: staging, promotion, reject, concurrent change."""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

import pytest

from opencobalt.personal_ai.coding import CodingMissionStore
from opencobalt.personal_ai.providers import ProviderRequest
from opencobalt.personal_ai.staging import PromotionConflictError, StagingController
from tests.test_live_cursor_coding import _allow_pending, _live_stack

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENCOBALT_LIVE_ACP") != "1",
    reason="live ACP smoke is opt-in via OPENCOBALT_LIVE_ACP=1",
)


def _committed_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    (path / "test_app.py").write_text(
        "from app import value\n\ndef test_value():\n    assert value() == 1\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, capture_output=True)
    return path


def _run_agent(tmp_path: Path, repo: Path, message: str):
    coordinator, engine, provider, store, missions = _live_stack(tmp_path)
    coding = CodingMissionStore(store, missions).create(
        objective=message,
        repository_path=str(repo),
        conversation_id="conv-live-contain",
        route_id="route-live-contain",
        capability_role="coding_agent",
        provider_id="cursor",
    )
    threading.Thread(target=_allow_pending, args=(coordinator,), daemon=True).start()
    result = provider.execute(
        ProviderRequest(
            message=message,
            cwd=str(repo),
            timeout_seconds=300,
            metadata={
                "capability_role": "coding_agent",
                "chat_surface": "coding_mission",
                "execution_id": "chatx-live-contain",
                "mission_id": coding["mission_id"],
                "coding_mission_id": coding["coding_id"],
                "route_id": "route-live-contain",
            },
        )
    )
    return result, store, engine, coding


def test_live_staging_then_promotion_then_reject_and_conflict(tmp_path: Path):
    repo = _committed_repo(tmp_path / "contain-repo")
    original = (repo / "app.py").read_text(encoding="utf-8")
    result, store, engine, coding = _run_agent(
        tmp_path,
        repo,
        "Add a function named answer that returns 42 and add a test for it.",
    )
    assert result.status in {"complete", "failed", "cancelled"}, result.error
    assert (repo / "app.py").read_text(encoding="utf-8") == original
    changeset = result.metadata.get("changeset") or {}
    assert changeset.get("changeset_id")
    assert changeset.get("promotion_state") in {"pending", "empty", "blocked"}
    if result.receipt_id:
        receipt = engine.store.get_receipt(result.receipt_id)
        assert receipt is not None
        assert any(str(ref).startswith("changeset:") for ref in (receipt.provenance_refs or []))
    if changeset.get("promotion_state") != "pending":
        pytest.skip(f"Cursor did not produce a pending ChangeSet: {changeset.get('promotion_state')}")
    controller = StagingController(
        store,
        staging_root=tmp_path / "staging",
    )
    applied = controller.apply_changeset(changeset["changeset_id"])
    assert applied.promotion_state == "applied"
    assert "42" in (repo / "app.py").read_text(encoding="utf-8")

    reject_repo = _committed_repo(tmp_path / "reject-repo")
    reject_original = (reject_repo / "app.py").read_text(encoding="utf-8")
    rejected_result, reject_store, _engine, _coding = _run_agent(
        tmp_path / "reject-stack",
        reject_repo,
        "Add a function named answer that returns 7.",
    )
    rejected_cs = rejected_result.metadata.get("changeset") or {}
    if rejected_cs.get("promotion_state") == "pending":
        StagingController(reject_store, staging_root=tmp_path / "reject-stack" / "staging").reject_changeset(
            rejected_cs["changeset_id"]
        )
        assert (reject_repo / "app.py").read_text(encoding="utf-8") == reject_original
        loaded = StagingController(reject_store, staging_root=tmp_path / "reject-stack" / "staging").get_changeset(
            rejected_cs["changeset_id"]
        )
        assert loaded.promotion_state == "rejected"

    conflict_repo = _committed_repo(tmp_path / "conflict-repo")
    conflict_result, conflict_store, _engine2, _coding2 = _run_agent(
        tmp_path / "conflict-stack",
        conflict_repo,
        "Add a function named answer that returns 42.",
    )
    conflict_cs = conflict_result.metadata.get("changeset") or {}
    if conflict_cs.get("promotion_state") == "pending":
        (conflict_repo / "unrelated.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "unrelated.py"], cwd=conflict_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "concurrent"], cwd=conflict_repo, check=True, capture_output=True)
        user_file = (conflict_repo / "unrelated.py").read_text(encoding="utf-8")
        with pytest.raises(PromotionConflictError, match="Repository changed"):
            StagingController(
                conflict_store, staging_root=tmp_path / "conflict-stack" / "staging"
            ).apply_changeset(conflict_cs["changeset_id"])
        assert (conflict_repo / "unrelated.py").read_text(encoding="utf-8") == user_file
