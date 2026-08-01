"""Bounded local skill inspection and installation without code execution."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

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


class InstalledSkill(BaseModel):
    skill: SkillRecord
    version: SkillVersion
    receipt_id: str


@dataclass(frozen=True)
class _PendingPreview:
    source: Path
    preview: SkillImportPreview


class SkillImportService:
    """Two-step local import: inspect first, then copy an exact approved tree."""

    def __init__(
        self,
        *,
        store: PersonalAIStore,
        ledger: Ledger,
        install_root: Path | None = None,
    ) -> None:
        self.store = store
        self.ledger = ledger
        self.install_root = (
            install_root or Path(".opencobalt") / "skills" / "imported"
        ).expanduser()
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
        self._pending[preview.preview_id] = _PendingPreview(
            source=resolved,
            preview=preview,
        )
        return preview

    def install(self, preview_id: str, *, approved: bool) -> InstalledSkill:
        pending = self._pending.get(preview_id)
        if pending is None:
            raise KeyError("unknown or expired skill preview")
        expected = pending.preview
        if expected.requires_approval and not approved:
            raise PermissionError("this skill import requires explicit approval")

        current = self._inspect(pending.source)
        if current.model_dump(exclude={"preview_id"}) != expected.model_dump(
            exclude={"preview_id"}
        ):
            raise ValueError("skill source changed since preview; inspect it again")

        root = self._resolved_install_root()
        destination = (
            root / expected.name / f"{expected.version}-{expected.content_hash[:12]}"
        ).resolve()
        self._require_bounded_path(destination, root)
        if destination.exists():
            if not destination.is_dir() or self._tree_hash(destination)[0] != expected.content_hash:
                raise ValueError("existing install path does not match the approved skill tree")
        else:
            self._copy_verified_tree(pending.source, destination, expected.content_hash)

        existing = self.store.get_skill_by_name(expected.name)
        if existing is not None and existing.source_kind != "imported":
            if destination.exists():
                shutil.rmtree(destination)
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
                "approved": approved,
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
        try:
            self.store.save_skill(skill)
            self.store.save_skill_version(version)
            self.ledger.insert_event(receipt)
        except Exception:
            # The copied tree is safe but incomplete state should not look installed.
            if destination.exists():
                shutil.rmtree(destination)
            raise
        self._pending.pop(preview_id, None)
        saved = self.store.get_skill(skill.skill_id)
        return InstalledSkill(
            skill=saved or skill,
            version=version,
            receipt_id=receipt.id,
        )

    def rollback(
        self,
        skill_id: str,
        skill_version_id: str,
        *,
        approved: bool,
    ) -> SkillRecord:
        if not approved:
            raise PermissionError("skill rollback requires explicit approval")
        skill, version = self._owned_imported_version(skill_id, skill_version_id)
        install_path = self._bounded_install_path(version)
        if not install_path.is_dir():
            raise ValueError("the requested skill version is not installed")
        activated = self.store.activate_skill_version(skill.skill_id, version.skill_version_id)
        receipt = SessionEvent(
            project="opencobalt",
            source="personal-ai-skill-import",
            event_type="skill.rolled_back",
            summary=f"Activated pinned skill version {version.version} for {skill.name}",
            metadata={
                "skill_id": skill.skill_id,
                "skill_version_id": version.skill_version_id,
                "content_hash": version.content_hash,
            },
        )
        self.ledger.insert_event(receipt)
        return activated

    def remove_version(
        self,
        skill_id: str,
        skill_version_id: str,
        *,
        approved: bool,
    ) -> str:
        if not approved:
            raise PermissionError("skill removal requires explicit approval")
        skill, version = self._owned_imported_version(skill_id, skill_version_id)
        if skill.active_version_id == version.skill_version_id:
            raise ValueError("rollback to another version before removing the active version")
        install_path = self._bounded_install_path(version)
        existed = install_path.exists()
        if existed:
            if not install_path.is_dir() or install_path.is_symlink():
                raise ValueError("refusing to remove an ambiguous skill install path")
            shutil.rmtree(install_path)
        receipt = SessionEvent(
            project="opencobalt",
            source="personal-ai-skill-import",
            event_type="skill.version_removed",
            summary=f"Removed local files for skill {skill.name} version {version.version}",
            metadata={
                "skill_id": skill.skill_id,
                "skill_version_id": version.skill_version_id,
                "content_hash": version.content_hash,
                "files_existed": existed,
            },
        )
        self.ledger.insert_event(receipt)
        return receipt.id

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
            stat_result = entry.stat(follow_symlinks=False)
            size = stat_result.st_size
            if size > _MAX_FILE_BYTES:
                raise ValueError("skill source contains an oversized file")
            total_bytes += size
            if total_bytes > _MAX_TOTAL_BYTES:
                raise ValueError("skill source is too large")
            data = entry.read_bytes()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(size).encode("ascii"))
            digest.update(b"\0")
            digest.update(oct(stat_result.st_mode & 0o777).encode("ascii"))
            digest.update(b"\0")
            digest.update(data)
            digest.update(b"\0")
            if entry.suffix.lower() in _EXECUTABLE_SUFFIXES or os.access(entry, os.X_OK):
                executable_files.append(relative)
        if not files:
            raise ValueError("skill source is empty")
        return digest.hexdigest(), files, executable_files, total_bytes

    def _copy_verified_tree(
        self, source: Path, destination: Path, expected_hash: str
    ) -> None:
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

    def _bounded_install_path(self, version: SkillVersion) -> Path:
        if version.install_path is None:
            raise ValueError("skill version has no local install path")
        root = self._resolved_install_root()
        path = Path(version.install_path).expanduser().resolve()
        self._require_bounded_path(path, root)
        return path
