"""Bounded local skill inspection and installation without code execution."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from opencobalt.core.approval_bridge import (
    ApprovalBridge,
    ApprovalRequest,
    ApprovalStep,
)
from opencobalt.core.ledger import Ledger
from opencobalt.core.models import SessionEvent

from .models import SkillRecord, SkillVersion
from .store import PersonalAIStore

_MAX_MANIFEST_BYTES = 64 * 1024
_MAX_FILE_BYTES = 512 * 1024
_MAX_TOTAL_BYTES = 2 * 1024 * 1024
_MAX_FILES = 128
_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_PERMISSION_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_EXECUTABLE_SUFFIXES = {
    ".bash",
    ".command",
    ".fish",
    ".js",
    ".mjs",
    ".pl",
    ".ps1",
    ".py",
    ".rb",
    ".sh",
    ".ts",
}
_HIGH_RISK_PERMISSIONS = {
    "browser",
    "credential_access",
    "external_runtime",
    "network",
    "secrets",
    "shell",
    "write_workspace",
}


class SkillImportPreview(BaseModel):
    preview_id: str
    source_name: str
    name: str
    version: str
    description: str
    content_hash: str
    files: list[str]
    executable_files: list[str]
    requested_permissions: list[str]
    compatibility: dict[str, Any] = Field(default_factory=dict)
    trust_level: Literal["low", "meaningful", "high"]
    trust_reasons: list[str]
    requires_approval: bool
    approval_request_id: str | None = None
    approval_step_id: str | None = None


class InstalledSkill(BaseModel):
    skill: SkillRecord
    version: SkillVersion
    receipt_id: str
    approval_decision_id: str | None = None


class SkillActionApproval(BaseModel):
    action: Literal["rollback", "remove"]
    skill_id: str
    skill_version_id: str
    approval_request_id: str
    approval_step_id: str


@dataclass(frozen=True)
class _PendingPreview:
    source: Path
    preview: SkillImportPreview


@dataclass(frozen=True)
class _ApprovalLink:
    approval_request_id: str
    approval_step_id: str


class SkillImportService:
    """Two-step local import: inspect first, then copy an exact approved tree."""

    def __init__(
        self,
        *,
        store: PersonalAIStore,
        ledger: Ledger,
        install_root: Path | None = None,
        approval_bridge: ApprovalBridge | None = None,
    ) -> None:
        self.store = store
        self.ledger = ledger
        if self.ledger.db_path != self.store.db_path:
            raise ValueError("skill store and ledger must share one SQLite database")
        self.install_root = (
            install_root or Path(".opencobalt") / "skills" / "imported"
        ).expanduser()
        self.approval_bridge = approval_bridge or ApprovalBridge(
            db_path=self.store.db_path,
            events_path=self.store.db_path.parent / "events" / "approval.jsonl",
        )
        if self.approval_bridge.store.db_path != self.store.db_path:
            raise ValueError("approval bridge must share the skill ledger database")
        self._pending: dict[str, _PendingPreview] = {}

    def preview(self, source: str | Path) -> SkillImportPreview:
        source_path = Path(source).expanduser()
        if source_path.is_symlink():
            raise ValueError("skill source cannot be a symlink")
        try:
            resolved = source_path.resolve(strict=True)
        except OSError as exc:
            raise ValueError("skill source does not exist") from exc
        if not resolved.is_dir():
            raise ValueError("skill source must be a directory")

        preview = self._inspect(resolved)
        if preview.requires_approval:
            approval = self._create_approval(
                action="import",
                source_id=f"skill-import:{preview.content_hash}",
                task=(
                    f"Import disabled skill {preview.name} version {preview.version} "
                    f"with trust level {preview.trust_level}"
                ),
                risk_level="red" if preview.trust_level == "high" else "yellow",
                metadata={
                    "skill_name": preview.name,
                    "skill_version": preview.version,
                    "content_hash": preview.content_hash,
                    "requested_permissions": preview.requested_permissions,
                    "executable_files": preview.executable_files,
                },
            )
            preview = preview.model_copy(
                update={
                    "approval_request_id": approval.approval_request_id,
                    "approval_step_id": approval.approval_step_id,
                }
            )
        self._pending[preview.preview_id] = _PendingPreview(
            source=resolved,
            preview=preview,
        )
        return preview

    def install(
        self,
        preview_id: str,
        *,
        approval_request_id: str | None = None,
    ) -> InstalledSkill:
        pending = self._pending.get(preview_id)
        if pending is None:
            raise KeyError("unknown or expired skill preview")
        expected = pending.preview
        approval_decision_id = None
        if expected.requires_approval:
            approval_decision_id = self._require_approval(
                approval_request_id,
                expected_action="import",
                expected_source_id=f"skill-import:{expected.content_hash}",
            )

        current = self._inspect(pending.source)
        approval_fields = {"preview_id", "approval_request_id", "approval_step_id"}
        if current.model_dump(exclude=approval_fields) != expected.model_dump(
            exclude=approval_fields
        ):
            raise ValueError("skill source changed since preview; inspect it again")

        root = self._resolved_install_root()
        destination = root / expected.name / f"{expected.version}-{expected.content_hash[:12]}"
        self._require_bounded_path(destination, root)
        if destination.parent.is_symlink():
            raise ValueError("skill install directory cannot be a symlink")
        existing = self.store.get_skill_by_name(expected.name)
        if existing is not None and existing.source_kind != "imported":
            raise ValueError("an existing built-in or user skill uses this name")
        skill = (
            existing.model_copy(
                update={
                    "description": expected.description,
                    "source_ref": f"local-tree:{expected.content_hash}",
                    "enabled": False,
                    "trust_level": expected.trust_level,
                    "requested_permissions": expected.requested_permissions,
                    "compatibility": expected.compatibility,
                }
            )
            if existing is not None
            else SkillRecord(
                name=expected.name,
                description=expected.description,
                source_kind="imported",
                source_ref=f"local-tree:{expected.content_hash}",
                enabled=False,
                trust_level=expected.trust_level,
                requested_permissions=expected.requested_permissions,
                compatibility=expected.compatibility,
            )
        )
        receipt = SessionEvent(
            project="opencobalt",
            source="personal-ai-skill-import",
            event_type="skill.imported",
            summary=f"Imported disabled skill {expected.name} at pinned version {expected.version}",
            metadata={
                "skill_id": skill.skill_id,
                "version": expected.version,
                "content_hash": expected.content_hash,
                "trust_level": expected.trust_level,
                "approval_required": expected.requires_approval,
                "approval_request_id": approval_request_id,
                "approval_decision_id": approval_decision_id,
                "executable_file_count": len(expected.executable_files),
                "requested_permissions": expected.requested_permissions,
            },
        )
        version = SkillVersion(
            skill_id=skill.skill_id,
            version=expected.version,
            content_hash=expected.content_hash,
            manifest={
                "name": expected.name,
                "description": expected.description,
                "permissions": expected.requested_permissions,
                "compatibility": expected.compatibility,
                "files": expected.files,
                "executable_files": expected.executable_files,
                "trust_reasons": expected.trust_reasons,
            },
            install_path=str(destination),
            receipt_id=receipt.id,
        )
        if existing is not None:
            installed = self.store.get_skill_version_by_identity(
                existing.skill_id,
                expected.version,
                expected.content_hash,
            )
            if installed is not None:
                self._verified_install_path(existing, installed)
                self._pending.pop(preview_id, None)
                return InstalledSkill(
                    skill=self.store.get_skill(existing.skill_id) or existing,
                    version=installed,
                    receipt_id=installed.receipt_id or receipt.id,
                    approval_decision_id=approval_decision_id,
                )

        created_destination = False
        if destination.exists() or destination.is_symlink():
            self._validate_existing_destination(destination, expected.content_hash)
        else:
            self._copy_verified_tree(pending.source, destination, expected.content_hash)
            created_destination = True
        try:
            self.store.save_imported_skill_with_receipt(skill, version, receipt)
        except Exception:
            # Compensate only a tree created by this invocation. A matching
            # pre-existing install must never be removed on a database failure.
            if created_destination and destination.exists():
                shutil.rmtree(destination)
            raise
        self._pending.pop(preview_id, None)
        saved = self.store.get_skill(skill.skill_id)
        return InstalledSkill(
            skill=saved or skill,
            version=version,
            receipt_id=receipt.id,
            approval_decision_id=approval_decision_id,
        )

    def rollback(
        self,
        skill_id: str,
        skill_version_id: str,
        *,
        approval_request_id: str,
    ) -> SkillRecord:
        skill, version = self._owned_imported_version(skill_id, skill_version_id)
        source_id = self._version_action_source_id("rollback", skill, version)
        decision_id = self._require_approval(
            approval_request_id,
            expected_action="rollback",
            expected_source_id=source_id,
        )
        self._verified_install_path(skill, version)
        receipt = SessionEvent(
            project="opencobalt",
            source="personal-ai-skill-import",
            event_type="skill.rolled_back",
            summary=f"Activated pinned skill version {version.version} for {skill.name}",
            metadata={
                "skill_id": skill.skill_id,
                "skill_version_id": version.skill_version_id,
                "content_hash": version.content_hash,
                "approval_request_id": approval_request_id,
                "approval_decision_id": decision_id,
            },
        )
        return self.store.activate_skill_version_with_receipt(
            skill.skill_id,
            version.skill_version_id,
            receipt,
        )

    def remove_version(
        self,
        skill_id: str,
        skill_version_id: str,
        *,
        approval_request_id: str,
    ) -> str:
        skill, version = self._owned_imported_version(skill_id, skill_version_id)
        if skill.active_version_id == version.skill_version_id:
            raise ValueError("rollback to another version before removing the active version")
        source_id = self._version_action_source_id("remove", skill, version)
        decision_id = self._require_approval(
            approval_request_id,
            expected_action="remove",
            expected_source_id=source_id,
        )
        install_path = self._verified_install_path(skill, version)
        quarantine = install_path.with_name(f".removed-{uuid.uuid4().hex}")
        self._require_bounded_path(quarantine, self._resolved_install_root())
        install_path.rename(quarantine)
        receipt = SessionEvent(
            project="opencobalt",
            source="personal-ai-skill-import",
            event_type="skill.version_removed",
            summary=f"Removed local files for skill {skill.name} version {version.version}",
            metadata={
                "skill_id": skill.skill_id,
                "skill_version_id": version.skill_version_id,
                "content_hash": version.content_hash,
                "approval_request_id": approval_request_id,
                "approval_decision_id": decision_id,
            },
        )
        try:
            # The canonical version disappears before the durable event. If
            # persistence fails, rename restores the exact verified tree.
            self.store.record_event(receipt)
        except Exception:
            quarantine.rename(install_path)
            raise
        try:
            shutil.rmtree(quarantine)
        except OSError:
            # The version is already absent from its canonical location and
            # durably receipted. A bounded quarantine is safer than rollback
            # after the committed decision.
            pass
        return receipt.id

    def request_version_action(
        self,
        skill_id: str,
        skill_version_id: str,
        *,
        action: Literal["rollback", "remove"],
    ) -> SkillActionApproval:
        skill, version = self._owned_imported_version(skill_id, skill_version_id)
        self._verified_install_path(skill, version)
        if action == "remove" and skill.active_version_id == version.skill_version_id:
            raise ValueError("rollback to another version before removing the active version")
        approval = self._create_approval(
            action=action,
            source_id=self._version_action_source_id(action, skill, version),
            task=(
                f"{action.title()} imported skill {skill.name} at pinned version "
                f"{version.version}"
            ),
            risk_level="red" if action == "remove" else "yellow",
            metadata={
                "skill_id": skill.skill_id,
                "skill_version_id": version.skill_version_id,
                "content_hash": version.content_hash,
            },
        )
        return SkillActionApproval(
            action=action,
            skill_id=skill.skill_id,
            skill_version_id=version.skill_version_id,
            approval_request_id=approval.approval_request_id,
            approval_step_id=approval.approval_step_id,
        )

    @staticmethod
    def online_discovery_status() -> dict[str, bool | str]:
        return {
            "available": False,
            "reason": "online skill discovery is not enabled in this local MVP",
        }

    def _inspect(self, source: Path) -> SkillImportPreview:
        content_hash, files, executable_files, total_bytes = self._tree_hash(source)
        manifest_path = source / "skill.json"
        if "skill.json" not in files:
            raise ValueError("skill.json manifest is required")
        if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
            raise ValueError("skill manifest is too large")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("skill manifest must be valid UTF-8 JSON") from exc
        if not isinstance(manifest, dict):
            raise ValueError("skill manifest must be an object")
        if self._tree_hash(source)[0] != content_hash:
            raise ValueError("skill source changed while it was being inspected")

        name = manifest.get("name")
        version = manifest.get("version")
        description = manifest.get("description", "")
        permissions = manifest.get("permissions", [])
        compatibility = manifest.get("compatibility", {})
        if not isinstance(name, str) or _NAME_PATTERN.fullmatch(name) is None:
            raise ValueError("skill name must be a bounded lowercase slug")
        if not isinstance(version, str) or _VERSION_PATTERN.fullmatch(version) is None:
            raise ValueError("skill version is invalid")
        if not isinstance(description, str) or len(description) > 400:
            raise ValueError("skill description must be at most 400 characters")
        if (
            not isinstance(permissions, list)
            or len(permissions) > 32
            or any(
                not isinstance(item, str) or _PERMISSION_PATTERN.fullmatch(item) is None
                for item in permissions
            )
        ):
            raise ValueError("skill permissions must be bounded identifiers")
        permissions = sorted(set(permissions))
        if not isinstance(compatibility, dict):
            raise ValueError("skill compatibility must be an object")

        trust_reasons = [f"inspected {len(files)} files totaling {total_bytes} bytes"]
        if executable_files:
            trust_reasons.append(
                f"contains {len(executable_files)} executable-content file(s)"
            )
        if permissions:
            trust_reasons.append("requests: " + ", ".join(permissions))
        high_risk = bool(_HIGH_RISK_PERMISSIONS.intersection(permissions))
        trust_level: Literal["low", "meaningful", "high"] = (
            "high" if high_risk else "meaningful" if executable_files or permissions else "low"
        )
        if trust_level == "low":
            trust_reasons.append("instructions and metadata only; no permissions requested")
        return SkillImportPreview(
            preview_id=f"skill-preview-{uuid.uuid4()}",
            source_name=source.name,
            name=name,
            version=version,
            description=description.strip(),
            content_hash=content_hash,
            files=files,
            executable_files=executable_files,
            requested_permissions=permissions,
            compatibility=compatibility,
            trust_level=trust_level,
            trust_reasons=trust_reasons,
            requires_approval=trust_level != "low",
        )

    @staticmethod
    def _tree_hash(source: Path) -> tuple[str, list[str], list[str], int]:
        digest = hashlib.sha256()
        files: list[str] = []
        executable_files: list[str] = []
        total_bytes = 0
        for entry in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
            if entry.is_symlink():
                raise ValueError("skill source cannot contain symlinks")
            if entry.is_dir():
                continue
            if not entry.is_file():
                raise ValueError("skill source can contain regular files only")
            relative = entry.relative_to(source).as_posix()
            if relative.startswith("../") or relative.startswith("/"):
                raise ValueError("skill source contains an unsafe path")
            files.append(relative)
            if len(files) > _MAX_FILES:
                raise ValueError("skill source contains too many files")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(entry, flags)
            except OSError as exc:
                raise ValueError("skill source changed while it was being inspected") from exc
            try:
                stat_result = os.fstat(descriptor)
                if not stat.S_ISREG(stat_result.st_mode):
                    raise ValueError("skill source can contain regular files only")
                chunks: list[bytes] = []
                remaining = _MAX_FILE_BYTES + 1
                while remaining:
                    chunk = os.read(descriptor, min(64 * 1024, remaining))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                data = b"".join(chunks)
            finally:
                os.close(descriptor)
            size = stat_result.st_size
            if size > _MAX_FILE_BYTES:
                raise ValueError("skill source contains an oversized file")
            total_bytes += size
            if total_bytes > _MAX_TOTAL_BYTES:
                raise ValueError("skill source is too large")
            if len(data) != size:
                raise ValueError("skill source changed while it was being inspected")
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(size).encode("ascii"))
            digest.update(b"\0")
            digest.update(oct(stat_result.st_mode & 0o777).encode("ascii"))
            digest.update(b"\0")
            digest.update(data)
            digest.update(b"\0")
            if entry.suffix.lower() in _EXECUTABLE_SUFFIXES or stat_result.st_mode & 0o111:
                executable_files.append(relative)
        if not files:
            raise ValueError("skill source is empty")
        return digest.hexdigest(), files, executable_files, total_bytes

    def _copy_verified_tree(
        self, source: Path, destination: Path, expected_hash: str
    ) -> None:
        if destination.parent.is_symlink():
            raise ValueError("skill install directory cannot be a symlink")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_path = Path(
            tempfile.mkdtemp(prefix=".import-", dir=str(destination.parent))
        ).resolve()
        self._require_bounded_path(temp_path, self._resolved_install_root())
        try:
            _, files, _, _ = self._tree_hash(source)
            for relative in files:
                target = temp_path / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / relative, target, follow_symlinks=False)
            copied_hash, _, _, _ = self._tree_hash(temp_path)
            if copied_hash != expected_hash:
                raise ValueError("skill source changed while it was being copied")
            if destination.parent.is_symlink():
                raise ValueError("skill install directory changed into a symlink")
            temp_path.rename(destination)
        except Exception:
            if temp_path.exists():
                shutil.rmtree(temp_path)
            raise

    def _resolved_install_root(self) -> Path:
        if self.install_root.is_symlink():
            raise ValueError("skill install root cannot be a symlink")
        self.install_root.mkdir(parents=True, exist_ok=True)
        root = self.install_root.resolve()
        return root

    @staticmethod
    def _require_bounded_path(path: Path, root: Path) -> None:
        if path == root or not path.is_relative_to(root):
            raise ValueError("skill install path escapes the bounded install root")

    def _owned_imported_version(
        self, skill_id: str, skill_version_id: str
    ) -> tuple[SkillRecord, SkillVersion]:
        skill = self.store.get_skill(skill_id)
        version = self.store.get_skill_version(skill_version_id)
        if skill is None or skill.source_kind != "imported":
            raise KeyError(f"unknown imported skill: {skill_id}")
        if version is None or version.skill_id != skill.skill_id:
            raise KeyError(f"unknown version for skill: {skill_version_id}")
        return skill, version

    def _validate_existing_destination(
        self,
        destination: Path,
        expected_hash: str,
    ) -> None:
        if destination.is_symlink():
            raise ValueError("existing skill install path cannot be a symlink")
        if not destination.is_dir():
            raise ValueError("existing skill install path is not a directory")
        if self._tree_hash(destination)[0] != expected_hash:
            raise ValueError("existing install path does not match the approved skill tree")

    def _verified_install_path(
        self,
        skill: SkillRecord,
        version: SkillVersion,
    ) -> Path:
        if version.install_path is None:
            raise ValueError("skill version has no local install path")
        root = self._resolved_install_root()
        skill_dir = root / skill.name
        if skill_dir.is_symlink():
            raise ValueError("skill install directory cannot be a symlink")
        expected = skill_dir / f"{version.version}-{version.content_hash[:12]}"
        raw_path = Path(version.install_path).expanduser()
        if raw_path.is_symlink():
            raise ValueError("skill version install path cannot be a symlink")
        if not raw_path.is_absolute():
            raw_path = raw_path.absolute()
        self._require_bounded_path(raw_path, root)
        if raw_path != expected or raw_path.resolve() != expected.resolve():
            raise ValueError("skill version install path is not the canonical pinned location")
        if not raw_path.is_dir():
            raise ValueError("the requested skill version is not installed")
        if self._tree_hash(raw_path)[0] != version.content_hash:
            raise ValueError("installed skill tree no longer matches its pinned content hash")
        return raw_path

    def _create_approval(
        self,
        *,
        action: str,
        source_id: str,
        task: str,
        risk_level: Literal["yellow", "red"],
        metadata: dict[str, Any],
    ) -> _ApprovalLink:
        request_id = f"aprq-skill-{uuid.uuid4().hex[:12]}"
        step_id = f"astp-skill-{uuid.uuid4().hex[:12]}"
        step = ApprovalStep(
            step_id=step_id,
            request_id=request_id,
            source_type="personal_ai_skill",
            source_id=source_id,
            task=task,
            risk_level=risk_level,
            permission_scope="write",
            approval_required=True,
            approval_state="pending",
            metadata={"action": action, **metadata},
        )
        request = ApprovalRequest(
            request_id=request_id,
            source_type="personal_ai_skill",
            source_id=source_id,
            run_id="personal-ai",
            goal_id="personal-ai-skill-safety",
            track_id=source_id,
            opportunity_plan_id="",
            goal_text=task,
            track_name=f"skill {action}",
            risk_level=risk_level,
            state="pending",
            steps=[step],
            metadata={"action": action, **metadata},
        )
        self.approval_bridge.store.save_request(request)
        return _ApprovalLink(
            approval_request_id=request_id,
            approval_step_id=step_id,
        )

    def _require_approval(
        self,
        approval_request_id: str | None,
        *,
        expected_action: str,
        expected_source_id: str,
    ) -> str:
        if not approval_request_id:
            raise PermissionError("an approved ApprovalBridge decision is required")
        request = self.approval_bridge.store.get_request(approval_request_id)
        if (
            request is None
            or request.request_id != approval_request_id
            or request.source_type != "personal_ai_skill"
            or request.source_id != expected_source_id
        ):
            raise PermissionError("the ApprovalBridge request does not authorize this action")
        approved_steps = [
            step
            for step in request.steps
            if step.approval_state == "approved"
            and step.metadata.get("action") == expected_action
        ]
        decisions = [
            decision
            for decision in self.approval_bridge.store.list_decisions(request.request_id)
            if decision.decision == "approved"
            and any(decision.step_id == step.step_id for step in approved_steps)
        ]
        if not approved_steps or not decisions:
            raise PermissionError("an approved ApprovalBridge decision is required")
        return decisions[-1].decision_id

    @staticmethod
    def _version_action_source_id(
        action: str,
        skill: SkillRecord,
        version: SkillVersion,
    ) -> str:
        return (
            f"skill-{action}:{skill.skill_id}:{version.skill_version_id}:"
            f"{version.content_hash}"
        )
