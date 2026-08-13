"""Staged workspace, ChangeSet, and promotion containment tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from opencobalt.core.approval_bridge import ApprovalStore
from opencobalt.execution.adapters import CursorAdapter
from opencobalt.personal_ai.cursor_acp import CursorACPProvider
from opencobalt.personal_ai.providers import ProviderRequest
from opencobalt.personal_ai.staging import (
    PromotionBlockedError,
    PromotionConflictError,
    PromotionStateError,
    StagingController,
    classify_path_policy,
)
from opencobalt.personal_ai.store import PersonalAIStore
from tests.test_cursor_acp import ACP_HELP, ScriptedSession, _acp_script


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_repo(path: Path, files: dict[str, str] | None = None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init"], path)
    _git(["config", "user.email", "test@example.com"], path)
    _git(["config", "user.name", "Test"], path)
    payload = files or {"app.py": "def value():\n    return 1\n"}
    for name, content in payload.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _git(["add", "-A"], path)
    _git(["commit", "-m", "initial"], path)
    return path


def _controller(tmp_path: Path) -> StagingController:
    store = PersonalAIStore(tmp_path / "ledger.db")
    return StagingController(
        store,
        staging_root=tmp_path / "staging",
        approval_store=ApprovalStore(tmp_path / "ledger.db"),
    )


def test_staged_workspace_leaves_authoritative_repo_unchanged(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    original = (repo / "app.py").read_text(encoding="utf-8")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    controller = _controller(tmp_path)
    workspace = controller.create_workspace(repo)
    assert workspace["kind"] == "git_worktree"
    assert workspace["head"] == head
    staged = Path(workspace["staging_path"])
    (staged / "app.py").write_text("def value():\n    return 99\n", encoding="utf-8")
    (staged / "extra.py").write_text("X = 1\n", encoding="utf-8")
    assert (repo / "app.py").read_text(encoding="utf-8") == original
    assert not (repo / "extra.py").exists()


def test_changeset_records_add_modify_and_delete(tmp_path: Path):
    repo = _init_repo(
        tmp_path / "repo",
        {"keep.py": "keep\n", "gone.py": "gone\n", "edit.py": "old\n"},
    )
    controller = _controller(tmp_path)
    workspace = controller.create_workspace(repo)
    staged = Path(workspace["staging_path"])
    (staged / "edit.py").write_text("new\n", encoding="utf-8")
    (staged / "gone.py").unlink()
    (staged / "added.py").write_text("added\n", encoding="utf-8")
    changeset = controller.generate_changeset(workspace, run_verification=False)
    kinds = {item.path: item.kind for item in changeset.files}
    assert kinds["added.py"] == "added"
    assert kinds["edit.py"] == "modified"
    assert kinds["gone.py"] == "deleted"
    assert changeset.summary["files_changed"] == 3
    assert changeset.diff_hash
    assert changeset.promotion_state == "pending"


def test_unsolicited_staged_write_does_not_mutate_authoritative_repo(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    original = (repo / "app.py").read_text(encoding="utf-8")
    controller = _controller(tmp_path)
    workspace = controller.create_workspace(repo)
    Path(workspace["staging_path"], "app.py").write_text(
        "def answer():\n    return 42\n", encoding="utf-8"
    )
    changeset = controller.generate_changeset(workspace, run_verification=False)
    assert (repo / "app.py").read_text(encoding="utf-8") == original
    assert any(item.path == "app.py" for item in changeset.files)


def test_path_policy_blocks_traversal_and_sensitive_files(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    assert classify_path_policy("../secret", repository=repo)["blocked"]
    assert classify_path_policy(".env", repository=repo)["blocked"]
    assert classify_path_policy(".git/config", repository=repo)["blocked"]
    assert classify_path_policy(".ssh/id_rsa", repository=repo)["blocked"]
    assert classify_path_policy(".opencobalt/ledger.db", repository=repo)["blocked"]
    assert not classify_path_policy("src/app.py", repository=repo)["blocked"]


def test_sensitive_path_blocks_promotion(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    controller = _controller(tmp_path)
    workspace = controller.create_workspace(repo)
    (Path(workspace["staging_path"]) / ".env").write_text("SECRET=1\n", encoding="utf-8")
    changeset = controller.generate_changeset(workspace, run_verification=False)
    assert changeset.promotion_state == "blocked"
    with pytest.raises(PromotionBlockedError):
        controller.apply_changeset(changeset.changeset_id)


def test_promotion_apply_and_reject(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    controller = _controller(tmp_path)
    workspace = controller.create_workspace(repo)
    Path(workspace["staging_path"], "app.py").write_text("def answer():\n    return 42\n")
    changeset = controller.generate_changeset(workspace, run_verification=False)
    controller.create_promotion_request(changeset)
    applied = controller.apply_changeset(changeset.changeset_id, reason="apply")
    assert applied.promotion_state == "applied"
    assert "42" in (repo / "app.py").read_text(encoding="utf-8")
    with pytest.raises(PromotionStateError, match="duplicate"):
        controller.apply_changeset(changeset.changeset_id)

    repo2 = _init_repo(tmp_path / "repo2")
    original = (repo2 / "app.py").read_text(encoding="utf-8")
    workspace2 = controller.create_workspace(repo2)
    Path(workspace2["staging_path"], "app.py").write_text("def answer():\n    return 7\n")
    rejected = controller.generate_changeset(workspace2, run_verification=False)
    controller.reject_changeset(rejected.changeset_id, reason="no")
    assert (repo2 / "app.py").read_text(encoding="utf-8") == original
    loaded = controller.get_changeset(rejected.changeset_id)
    assert loaded.promotion_state == "rejected"
    with pytest.raises(PromotionStateError, match="already rejected"):
        controller.apply_changeset(rejected.changeset_id)


def test_head_change_and_dirty_overlap_fail_closed(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    controller = _controller(tmp_path)
    workspace = controller.create_workspace(repo)
    Path(workspace["staging_path"], "app.py").write_text("def answer():\n    return 42\n")
    changeset = controller.generate_changeset(workspace, run_verification=False)
    (repo / "other.py").write_text("other\n", encoding="utf-8")
    _git(["add", "other.py"], repo)
    _git(["commit", "-m", "move head"], repo)
    with pytest.raises(PromotionConflictError, match="Repository changed"):
        controller.apply_changeset(changeset.changeset_id)
    assert "return 1" in (repo / "app.py").read_text(encoding="utf-8")

    repo2 = _init_repo(tmp_path / "dirty")
    workspace2 = controller.create_workspace(repo2)
    Path(workspace2["staging_path"], "app.py").write_text("def answer():\n    return 3\n")
    dirty = controller.generate_changeset(workspace2, run_verification=False)
    (repo2 / "app.py").write_text("def value():\n    return 'user edit'\n", encoding="utf-8")
    with pytest.raises(PromotionConflictError, match="uncommitted"):
        controller.apply_changeset(dirty.changeset_id)
    assert "user edit" in (repo2 / "app.py").read_text(encoding="utf-8")


def test_dirty_repository_is_recorded_and_not_reset(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    (repo / "app.py").write_text("def value():\n    return 'dirty'\n", encoding="utf-8")
    dirty_text = (repo / "app.py").read_text(encoding="utf-8")
    controller = _controller(tmp_path)
    workspace = controller.create_workspace(repo)
    assert workspace["dirty_paths"]
    assert "app.py" in workspace["dirty_paths"][0] or "app.py" in "".join(workspace["dirty_paths"])
    staged = Path(workspace["staging_path"]) / "app.py"
    assert "return 1" in staged.read_text(encoding="utf-8")
    assert (repo / "app.py").read_text(encoding="utf-8") == dirty_text


def test_verification_persists_pytest_result(tmp_path: Path):
    repo = _init_repo(
        tmp_path / "repo",
        {
            "app.py": "def answer():\n    return 42\n",
            "test_app.py": "from app import answer\n\ndef test_answer():\n    assert answer() == 42\n",
        },
    )
    controller = _controller(tmp_path)
    workspace = controller.create_workspace(repo)
    changeset = controller.generate_changeset(workspace, run_verification=True)
    assert changeset.verification["status"] == "passed"
    assert changeset.tests


def test_cleanup_preserves_pending_and_removes_finalized(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    controller = _controller(tmp_path)
    workspace = controller.create_workspace(repo)
    Path(workspace["staging_path"], "app.py").write_text("def answer():\n    return 42\n")
    changeset = controller.generate_changeset(workspace, run_verification=False)
    controller.cleanup_workspace(workspace["workspace_id"])
    assert Path(workspace["staging_path"]).exists()
    controller.reject_changeset(changeset.changeset_id)
    controller.cleanup_workspace(workspace["workspace_id"], force=True)
    assert not Path(workspace["staging_path"]).exists()
    assert controller.get_changeset(changeset.changeset_id).promotion_state == "rejected"


def test_cross_mission_promotion_is_rejected(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    controller = _controller(tmp_path)
    workspace = controller.create_workspace(repo, coding_id="cod-1", mission_id="mis-1")
    Path(workspace["staging_path"], "app.py").write_text("def answer():\n    return 42\n")
    changeset = controller.generate_changeset(
        workspace, coding_id="cod-1", mission_id="mis-1", run_verification=False
    )
    with pytest.raises(PromotionStateError, match="cross-Mission"):
        controller.apply_changeset(changeset.changeset_id, coding_id="cod-other")


class _MutatingEngine:
    def __init__(self, session: ScriptedSession, *, write_text: str) -> None:
        self.session = session
        self.write_text = write_text
        self.calls: list[dict] = []

    def run_task(self, task: str, **kwargs):
        self.calls.append({"task": task, **kwargs})
        cwd = Path(kwargs["cwd"])
        (cwd / "app.py").write_text(self.write_text, encoding="utf-8")
        handler = kwargs["session_handler"]
        payload = handler(self.session)
        stdout = json.dumps(payload)
        return SimpleNamespace(
            result=SimpleNamespace(
                status="succeeded",
                stdout_preview=stdout,
                stderr_preview="",
                error=None,
                usage=None,
                stdout_path=None,
                content=stdout,
            ),
            receipt=SimpleNamespace(receipt_id="receipt-contain", limitations=[], provenance_refs=[]),
            policy=SimpleNamespace(allowed=True, reason="allowed"),
        )


def test_cursor_coding_agent_writes_only_in_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _init_repo(tmp_path / "repo")
    original = (repo / "app.py").read_text(encoding="utf-8")
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
    store = PersonalAIStore(tmp_path / "ledger.db")
    engine = _MutatingEngine(
        ScriptedSession(_acp_script()),
        write_text="def answer():\n    return 42\n",
    )
    engine.store = store  # type: ignore[attr-defined]
    provider = CursorACPProvider(
        engine,
        adapter,
        store=store,
        staging_root=tmp_path / "staging",
        approval_store=ApprovalStore(tmp_path / "ledger.db"),
    )
    result = provider.execute(
        ProviderRequest(
            message="Add answer()",
            cwd=str(repo),
            metadata={"capability_role": "coding_agent", "chat_surface": "coding_mission"},
        )
    )
    assert result.status == "complete"
    assert (repo / "app.py").read_text(encoding="utf-8") == original
    assert engine.calls[0]["cwd"] != str(repo)
    assert Path(engine.calls[0]["cwd"]).is_relative_to(tmp_path / "staging")
    changeset = result.metadata["changeset"]
    assert changeset["promotion_state"] == "pending"
    assert any(item["path"] == "app.py" for item in changeset["files"])
    assert any("without an ACP permission request" in item for item in result.limitations)


def test_coding_analysis_does_not_create_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = _init_repo(tmp_path / "repo")
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
    engine = _MutatingEngine(
        ScriptedSession(_acp_script()),
        write_text="def value():\n    return 1\n",
    )
    provider = CursorACPProvider(engine, adapter, staging_root=tmp_path / "staging")
    result = provider.execute(
        ProviderRequest(
            message="explain app.py",
            cwd=str(repo),
            metadata={"capability_role": "coding_analysis"},
        )
    )
    assert result.status == "complete"
    assert engine.calls[0]["cwd"] == str(repo)
    assert "changeset" not in result.metadata


def test_changeset_http_apply_reject_and_conflicts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    from opencobalt.api_server import app

    monkeypatch.chdir(tmp_path)
    repo = _init_repo(tmp_path / "repo")
    db = tmp_path / ".opencobalt" / "ledger.db"
    store = PersonalAIStore(db)
    controller = StagingController(
        store,
        staging_root=tmp_path / ".opencobalt" / "staging",
        approval_store=ApprovalStore(db),
    )
    workspace = controller.create_workspace(repo, coding_id="cod-http", mission_id="mis-http")
    Path(workspace["staging_path"], "app.py").write_text("def answer():\n    return 42\n")
    changeset = controller.generate_changeset(
        workspace, coding_id="cod-http", mission_id="mis-http", run_verification=False
    )
    with TestClient(app) as client:
        listed = client.get(f"/api/v1/changesets/{changeset.changeset_id}")
        assert listed.status_code == 200
        assert listed.json()["promotion_state"] == "pending"
        assert listed.json().get("staging_path") in {None, ""}
        diff = client.get(f"/api/v1/changesets/{changeset.changeset_id}/diff")
        assert diff.status_code == 200
        assert "diff" in diff.json()
        applied = client.post(f"/api/v1/changesets/{changeset.changeset_id}/apply", json={"reason": "ok"})
        assert applied.status_code == 200, applied.text
        assert applied.json()["promotion_state"] == "applied"
        duplicate = client.post(f"/api/v1/changesets/{changeset.changeset_id}/apply", json={})
        assert duplicate.status_code == 409
        missing = client.get("/api/v1/changesets/chs-missing")
        assert missing.status_code == 404
    assert "42" in (repo / "app.py").read_text(encoding="utf-8")

    workspace2 = controller.create_workspace(repo, coding_id="cod-http-2")
    Path(workspace2["staging_path"], "app.py").write_text("def answer():\n    return 7\n")
    rejected = controller.generate_changeset(workspace2, coding_id="cod-http-2", run_verification=False)
    with TestClient(app) as client:
        denied = client.post(f"/api/v1/changesets/{rejected.changeset_id}/reject", json={"reason": "no"})
        assert denied.status_code == 200
        assert denied.json()["promotion_state"] == "rejected"
        again = client.post(f"/api/v1/changesets/{rejected.changeset_id}/apply", json={})
        assert again.status_code == 409


def test_pending_changeset_survives_store_restart(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    db = tmp_path / "ledger.db"
    first = StagingController(
        PersonalAIStore(db),
        staging_root=tmp_path / "staging",
        approval_store=ApprovalStore(db),
    )
    workspace = first.create_workspace(repo)
    Path(workspace["staging_path"], "app.py").write_text("def answer():\n    return 42\n")
    changeset = first.generate_changeset(workspace, run_verification=False)
    second = StagingController(
        PersonalAIStore(db),
        staging_root=tmp_path / "staging",
        approval_store=ApprovalStore(db),
    )
    loaded = second.get_changeset(changeset.changeset_id)
    assert loaded.promotion_state == "pending"
    applied = second.apply_changeset(loaded.changeset_id)
    assert applied.promotion_state == "applied"
    assert "42" in (repo / "app.py").read_text(encoding="utf-8")


def test_apply_fails_closed_if_staging_is_gone(tmp_path: Path):
    repo = _init_repo(tmp_path / "repo")
    original = (repo / "app.py").read_text(encoding="utf-8")
    controller = _controller(tmp_path)
    workspace = controller.create_workspace(repo)
    Path(workspace["staging_path"], "app.py").write_text("def answer():\n    return 42\n")
    changeset = controller.generate_changeset(workspace, run_verification=False)
    import shutil

    shutil.rmtree(workspace["staging_path"])
    with pytest.raises(PromotionConflictError, match="no longer available"):
        controller.apply_changeset(changeset.changeset_id)
    assert (repo / "app.py").read_text(encoding="utf-8") == original


def test_coding_analysis_flags_unexpected_authoritative_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = _init_repo(tmp_path / "repo")
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
    engine = _MutatingEngine(
        ScriptedSession(_acp_script()),
        write_text="def value():\n    return 99\n",
    )
    provider = CursorACPProvider(engine, adapter, staging_root=tmp_path / "staging")
    result = provider.execute(
        ProviderRequest(
            message="explain app.py",
            cwd=str(repo),
            metadata={"capability_role": "coding_analysis"},
        )
    )
    assert result.status == "complete"
    assert "changeset" not in result.metadata
    assert any("non-mutating" in item for item in result.limitations)
    assert result.metadata.get("files_changed")

