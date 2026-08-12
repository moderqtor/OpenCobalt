from __future__ import annotations

import json
from pathlib import Path

import pytest

from opencobalt.core.ledger import Ledger
from opencobalt.personal_ai.skill_import import SkillImportService
from opencobalt.personal_ai.store import PersonalAIStore


def _write_manifest(
    source: Path,
    *,
    name: str = "focused-review",
    version: str = "1.0.0",
    permissions: list[str] | None = None,
) -> None:
    source.mkdir(parents=True, exist_ok=True)
    (source / "skill.json").write_text(
        json.dumps(
            {
                "name": name,
                "version": version,
                "description": "A bounded local review procedure",
                "permissions": permissions or [],
                "compatibility": {"providers": ["codex-cli", "mock"]},
            }
        ),
        encoding="utf-8",
    )


def _service(tmp_path: Path) -> tuple[SkillImportService, PersonalAIStore, Ledger]:
    db_path = tmp_path / "ledger.db"
    store = PersonalAIStore(db_path)
    ledger = Ledger(db_path)
    service = SkillImportService(
        store=store,
        ledger=ledger,
        install_root=tmp_path / "installed-skills",
    )
    return service, store, ledger


def test_safe_local_import_is_pinned_disabled_and_receipted(tmp_path):
    source = tmp_path / "source"
    _write_manifest(source)
    (source / "SKILL.md").write_text("Review evidence, then report uncertainty.\n")
    service, store, ledger = _service(tmp_path)

    preview = service.preview(source)

    assert preview.name == "focused-review"
    assert preview.version == "1.0.0"
    assert preview.trust_level == "low"
    assert preview.requires_approval is False
    assert preview.executable_files == []
    assert len(preview.content_hash) == 64

    installed = service.install(preview.preview_id)

    assert installed.skill.enabled is False
    assert installed.skill.source_kind == "imported"
    assert installed.version.content_hash == preview.content_hash
    assert installed.version.receipt_id == installed.receipt_id
    install_path = Path(installed.version.install_path)
    assert install_path.is_relative_to((tmp_path / "installed-skills").resolve())
    assert (install_path / "SKILL.md").read_text() == (
        "Review evidence, then report uncertainty.\n"
    )
    assert store.list_skills()[0].active_version_id == installed.version.skill_version_id
    event = next(event for event in ledger.list_events() if event.id == installed.receipt_id)
    assert event.event_type == "skill.imported"
    assert preview.content_hash in event.metadata["content_hash"]


def test_executable_or_permission_risk_requires_approval_and_never_executes(tmp_path):
    source = tmp_path / "risky"
    _write_manifest(source, permissions=["network", "write_workspace"])
    marker = tmp_path / "must-not-exist"
    (source / "run.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
    )
    service, _, _ = _service(tmp_path)

    preview = service.preview(source)

    assert preview.trust_level == "high"
    assert preview.requires_approval is True
    assert preview.executable_files == ["run.py"]
    assert set(preview.requested_permissions) == {"network", "write_workspace"}
    assert preview.approval_request_id is not None
    assert preview.approval_step_id is not None
    with pytest.raises(PermissionError, match="ApprovalBridge"):
        service.install(preview.preview_id)
    assert marker.exists() is False

    service.approval_bridge.approve(preview.approval_request_id)
    installed = service.install(
        preview.preview_id,
        approval_request_id=preview.approval_request_id,
    )
    assert installed.approval_decision_id is not None
    assert marker.exists() is False


@pytest.mark.parametrize(
    "fixture",
    ["symlink", "unsafe_name", "oversized"],
)
def test_preview_rejects_unbounded_or_ambiguous_sources(tmp_path, fixture):
    source = tmp_path / fixture
    if fixture == "unsafe_name":
        _write_manifest(source, name="../escape")
    else:
        _write_manifest(source)
    if fixture == "symlink":
        target = tmp_path / "outside.txt"
        target.write_text("outside")
        (source / "linked.txt").symlink_to(target)
    if fixture == "oversized":
        (source / "large.bin").write_bytes(b"x" * (512 * 1024 + 1))
    service, _, _ = _service(tmp_path)

    with pytest.raises(ValueError):
        service.preview(source)


def test_install_rechecks_source_hash_to_prevent_preview_install_race(tmp_path):
    source = tmp_path / "mutable"
    _write_manifest(source)
    instructions = source / "SKILL.md"
    instructions.write_text("Original instructions")
    service, store, ledger = _service(tmp_path)
    preview = service.preview(source)

    instructions.write_text("Changed after review")

    with pytest.raises(ValueError, match="changed since preview"):
        service.install(preview.preview_id)
    assert store.list_skills() == []
    assert [event for event in ledger.list_events() if event.event_type == "skill.imported"] == []


def test_install_rechecks_executable_mode_after_preview(tmp_path):
    source = tmp_path / "mode-change"
    _write_manifest(source)
    script = source / "helper"
    script.write_text("#!/bin/sh\nprintf safe\n")
    script.chmod(0o600)
    service, _, _ = _service(tmp_path)
    preview = service.preview(source)
    assert preview.requires_approval is False

    script.chmod(0o700)

    with pytest.raises(ValueError, match="changed since preview"):
        service.install(preview.preview_id)


def test_install_root_cannot_be_redirected_through_a_symlink(tmp_path):
    source = tmp_path / "source"
    _write_manifest(source)
    (source / "SKILL.md").write_text("Safe instructions")
    outside = tmp_path / "outside-installs"
    outside.mkdir()
    install_link = tmp_path / "installed-skills"
    install_link.symlink_to(outside, target_is_directory=True)
    db_path = tmp_path / "ledger.db"
    service = SkillImportService(
        store=PersonalAIStore(db_path),
        ledger=Ledger(db_path),
        install_root=install_link,
    )
    preview = service.preview(source)

    with pytest.raises(ValueError, match="install root cannot be a symlink"):
        service.install(preview.preview_id)


def test_imported_versions_support_explicit_rollback_and_bounded_removal(tmp_path):
    source = tmp_path / "versioned"
    _write_manifest(source, version="1.0.0")
    (source / "SKILL.md").write_text("Version one")
    service, store, ledger = _service(tmp_path)
    first = service.install(service.preview(source).preview_id)

    _write_manifest(source, version="2.0.0")
    (source / "SKILL.md").write_text("Version two")
    second = service.install(service.preview(source).preview_id)
    assert store.get_skill(first.skill.skill_id).active_version_id == (
        second.version.skill_version_id
    )

    rollback_approval = service.request_version_action(
        first.skill.skill_id,
        first.version.skill_version_id,
        action="rollback",
    )
    service.approval_bridge.approve(rollback_approval.approval_request_id)
    rolled_back = service.rollback(
        first.skill.skill_id,
        first.version.skill_version_id,
        approval_request_id=rollback_approval.approval_request_id,
    )
    assert rolled_back.active_version_id == first.version.skill_version_id

    removal_approval = service.request_version_action(
        first.skill.skill_id,
        second.version.skill_version_id,
        action="remove",
    )
    service.approval_bridge.approve(removal_approval.approval_request_id)
    removed_receipt = service.remove_version(
        first.skill.skill_id,
        second.version.skill_version_id,
        approval_request_id=removal_approval.approval_request_id,
    )
    assert Path(second.version.install_path).exists() is False
    assert store.get_skill_version(second.version.skill_version_id) is not None
    assert any(event.id == removed_receipt for event in ledger.list_events())


def test_online_skill_discovery_is_truthfully_unavailable(tmp_path):
    service, _, _ = _service(tmp_path)

    status = service.online_discovery_status()

    assert status == {
        "available": False,
        "reason": "online skill discovery is not enabled in this local MVP",
    }


def test_identical_reimport_is_idempotent_and_never_deletes_existing_tree(tmp_path):
    source = tmp_path / "source"
    _write_manifest(source)
    (source / "SKILL.md").write_text("Pinned instructions")
    service, store, _ = _service(tmp_path)
    first = service.install(service.preview(source).preview_id)
    install_path = Path(first.version.install_path)

    second = service.install(service.preview(source).preview_id)

    assert second.version.skill_version_id == first.version.skill_version_id
    assert second.receipt_id == first.receipt_id
    assert install_path.is_dir()
    assert (install_path / "SKILL.md").read_text() == "Pinned instructions"
    assert len(store.list_skill_versions(first.skill.skill_id)) == 1


def test_symlink_substitution_cannot_redirect_rollback_or_removal(tmp_path):
    source = tmp_path / "versioned"
    _write_manifest(source, version="1.0.0")
    (source / "SKILL.md").write_text("Version one")
    service, _, _ = _service(tmp_path)
    first = service.install(service.preview(source).preview_id)
    _write_manifest(source, version="2.0.0")
    (source / "SKILL.md").write_text("Version two")
    second = service.install(service.preview(source).preview_id)

    rollback = service.request_version_action(
        first.skill.skill_id,
        first.version.skill_version_id,
        action="rollback",
    )
    service.approval_bridge.approve(rollback.approval_request_id)
    service.rollback(
        first.skill.skill_id,
        first.version.skill_version_id,
        approval_request_id=rollback.approval_request_id,
    )
    approval = service.request_version_action(
        first.skill.skill_id,
        second.version.skill_version_id,
        action="remove",
    )
    service.approval_bridge.approve(approval.approval_request_id)
    second_path = Path(second.version.install_path)
    second_path.rename(second_path.with_name(second_path.name + "-real"))
    second_path.symlink_to(Path(first.version.install_path), target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        service.remove_version(
            first.skill.skill_id,
            second.version.skill_version_id,
            approval_request_id=approval.approval_request_id,
        )
    assert Path(first.version.install_path).is_dir()
    assert second_path.is_symlink()


def test_bare_boolean_or_unrelated_approval_cannot_authorize_risky_import(tmp_path):
    source = tmp_path / "risky"
    _write_manifest(source, permissions=["network"])
    service, _, _ = _service(tmp_path)
    preview = service.preview(source)

    with pytest.raises((TypeError, PermissionError)):
        service.install(preview.preview_id, approved=True)
    with pytest.raises(PermissionError, match="ApprovalBridge"):
        service.install(preview.preview_id, approval_request_id="aprq-unrelated")


def test_database_receipt_failure_rolls_back_records_and_only_new_files(tmp_path, monkeypatch):
    source = tmp_path / "source"
    _write_manifest(source)
    (source / "SKILL.md").write_text("Atomic import")
    service, store, _ = _service(tmp_path)
    preview = service.preview(source)

    def fail_receipt(*_args, **_kwargs):
        raise RuntimeError("simulated receipt failure")

    monkeypatch.setattr(PersonalAIStore, "_insert_event", staticmethod(fail_receipt))
    with pytest.raises(RuntimeError, match="receipt failure"):
        service.install(preview.preview_id)

    assert store.list_skills() == []
    assert list((tmp_path / "installed-skills").rglob("SKILL.md")) == []


def test_removal_receipt_failure_restores_verified_canonical_tree(tmp_path, monkeypatch):
    source = tmp_path / "versioned"
    _write_manifest(source, version="1.0.0")
    (source / "SKILL.md").write_text("Version one")
    service, _, _ = _service(tmp_path)
    first = service.install(service.preview(source).preview_id)
    _write_manifest(source, version="2.0.0")
    (source / "SKILL.md").write_text("Version two")
    second = service.install(service.preview(source).preview_id)
    rollback = service.request_version_action(
        first.skill.skill_id,
        first.version.skill_version_id,
        action="rollback",
    )
    service.approval_bridge.approve(rollback.approval_request_id)
    service.rollback(
        first.skill.skill_id,
        first.version.skill_version_id,
        approval_request_id=rollback.approval_request_id,
    )
    removal = service.request_version_action(
        first.skill.skill_id,
        second.version.skill_version_id,
        action="remove",
    )
    service.approval_bridge.approve(removal.approval_request_id)

    def fail_event(_event):
        raise RuntimeError("simulated removal receipt failure")

    monkeypatch.setattr(store := service.store, "record_event", fail_event)
    with pytest.raises(RuntimeError, match="removal receipt failure"):
        service.remove_version(
            first.skill.skill_id,
            second.version.skill_version_id,
            approval_request_id=removal.approval_request_id,
        )

    restored = Path(second.version.install_path)
    assert restored.is_dir()
    assert restored.is_symlink() is False
    assert (restored / "SKILL.md").read_text() == "Version two"
    assert store.get_skill_version(second.version.skill_version_id) is not None
