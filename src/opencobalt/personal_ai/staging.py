"""Staged workspaces for coding-agent execution.

Providers may propose state. OpenCobalt commits authoritative state.

A staged workspace keeps incidental provider writes off the user's
authoritative repository. It does not provide OS-level filesystem isolation
if a provider process navigates elsewhere on the host.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opencobalt.core.approval_bridge import ApprovalRequest, ApprovalStep, ApprovalStore
from opencobalt.personal_ai.cursor_acp import (
    path_escapes_repository,
    validate_repository_path,
)

MAX_DIFF_CHARS = 512_000
STALE_WORKSPACE_HOURS = 24 * 7
CONTAINMENT_LIMITATION = (
    "Cursor executed against a staged workspace. Unsolicited writes in that "
    "workspace are not authoritative. This is not OS-level host sandboxing."
)
PROMOTION_SOURCE_TYPE = "coding_promotion"

_COPY_IGNORE = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".opencobalt",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

_SENSITIVE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".env.staging",
    "credentials.json",
    "credentials",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "authorized_keys",
    "known_hosts",
    "shadow",
    "gshadow",
}

_SENSITIVE_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".kdbx",
    ".sqlite",
    ".sqlite3",
}

_SENSITIVE_PARTS = {
    ".git",
    ".ssh",
    ".gnupg",
    ".aws",
    ".opencobalt",
    ".cursor",
    ".codex",
}

_SENSITIVE_NAME_MARKERS = (
    "credential",
    "secret",
    "private_key",
    "id_rsa",
    "id_ed25519",
    "auth.json",
    "session",
    "cookie",
    "token.json",
    "ledger.db",
    "telemetry.db",
)


class StagingError(Exception):
    """Base error for staged-workspace operations."""


class PromotionConflictError(StagingError):
    """Authoritative repository moved or has conflicting local edits."""


class PromotionBlockedError(StagingError):
    """ChangeSet contains path or policy violations."""


class PromotionStateError(StagingError):
    """Promotion was already decided, is stale, or does not match the Mission."""


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def _dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def default_staging_root(state_root: Path | None = None) -> Path:
    root = (state_root or Path(".opencobalt")).expanduser().resolve()
    return root / "staging"


def _git(
    args: list[str],
    *,
    cwd: Path,
    timeout: int = 30,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "git command failed").strip()[:400]
        raise StagingError(detail)
    return result


def inspect_repository(path: Path) -> dict[str, Any]:
    """Record authoritative starting state without mutating the working tree."""
    root = validate_repository_path(str(path))
    git_dir = _git(["rev-parse", "--is-inside-work-tree"], cwd=root)
    is_git = git_dir.returncode == 0 and git_dir.stdout.strip() == "true"
    head = None
    branch = None
    dirty_paths: list[str] = []
    toplevel = str(root)
    if is_git:
        top = _git(["rev-parse", "--show-toplevel"], cwd=root)
        if top.returncode == 0 and top.stdout.strip():
            toplevel = str(Path(top.stdout.strip()).resolve())
        head_result = _git(["rev-parse", "HEAD"], cwd=root)
        if head_result.returncode == 0:
            head = head_result.stdout.strip() or None
        branch_result = _git(["branch", "--show-current"], cwd=root)
        if branch_result.returncode == 0:
            branch = branch_result.stdout.strip() or None
        status = _git(["status", "--porcelain"], cwd=root)
        if status.returncode == 0:
            dirty_paths = [
                line[3:].strip()
                for line in status.stdout.splitlines()
                if line.strip()
            ]
    return {
        "repository_path": str(root),
        "repository_root": toplevel,
        "is_git": is_git,
        "head": head,
        "branch": branch,
        "dirty_paths": dirty_paths,
        "inspected_at": _iso(),
    }


def classify_path_policy(relative: str, *, repository: Path) -> dict[str, Any]:
    """Return path-policy findings for one proposed relative path."""
    posix = relative.replace("\\", "/")
    while posix.startswith("./"):
        posix = posix[2:]
    posix = posix.lstrip("/")
    invalid = (
        not posix
        or posix.startswith("/")
        or "\x00" in posix
        or any(part == ".." for part in Path(posix).parts)
        or path_escapes_repository(posix, repository)
    )
    parts = Path(posix).parts
    name = Path(posix).name
    lowered_name = name.casefold()
    lowered_path = posix.casefold()
    sensitive = False
    reasons: list[str] = []
    if invalid:
        reasons.append("path escapes the intended repository boundary")
    if any(part in _SENSITIVE_PARTS for part in parts):
        sensitive = True
        reasons.append("path includes a protected directory")
    if lowered_name in {item.casefold() for item in _SENSITIVE_NAMES}:
        sensitive = True
        reasons.append("filename matches a protected credential or environment file")
    suffix = Path(posix).suffix.casefold()
    if suffix in _SENSITIVE_SUFFIXES and (
        any(part.startswith(".") for part in parts)
        or any(marker in lowered_path for marker in _SENSITIVE_NAME_MARKERS)
        or suffix in {".pem", ".key", ".p12", ".pfx"}
    ):
        sensitive = True
        reasons.append("file looks like credential, key, or private database material")
    if any(marker in lowered_name or marker in lowered_path for marker in _SENSITIVE_NAME_MARKERS):
        sensitive = True
        reasons.append("path matches protected credential or runtime-state material")
    if posix == ".git" or posix.startswith(".git/"):
        sensitive = True
        invalid = True
        reasons.append(".git internals cannot be promoted")
    return {
        "path": posix,
        "invalid": invalid,
        "sensitive": sensitive,
        "blocked": invalid or sensitive,
        "reasons": list(dict.fromkeys(reasons)),
    }


@dataclass
class FileChange:
    path: str
    kind: str
    old_path: str | None = None
    binary: bool = False
    additions: int = 0
    deletions: int = 0
    blocked: bool = False
    sensitive: bool = False
    invalid: bool = False
    reasons: list[str] = field(default_factory=list)


@dataclass
class ChangeSet:
    changeset_id: str
    workspace_id: str
    coding_id: str | None
    mission_id: str | None
    execution_id: str | None
    provider_id: str
    runtime: str
    authoritative_path: str
    starting_head: str | None
    staging_path: str
    created_at: str
    files: list[FileChange] = field(default_factory=list)
    diff_text: str = ""
    diff_hash: str = ""
    binary_files: list[dict[str, Any]] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)
    promotion_state: str = "pending"
    apply_state: str | None = None
    promotion_request_id: str | None = None
    limitations: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    suspicious: list[str] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["files"] = [asdict(item) for item in self.files]
        return payload

    def public_view(self, *, include_diff: bool = False, technical: bool = False) -> dict[str, Any]:
        view = {
            "changeset_id": self.changeset_id,
            "workspace_id": self.workspace_id if technical else None,
            "coding_id": self.coding_id,
            "mission_id": self.mission_id,
            "execution_id": self.execution_id,
            "provider_id": self.provider_id,
            "runtime": self.runtime,
            "authoritative_path": self.authoritative_path,
            "starting_head": self.starting_head,
            "created_at": self.created_at,
            "updated_at": self.updated_at or self.created_at,
            "files": [asdict(item) for item in self.files],
            "diff_hash": self.diff_hash,
            "binary_files": list(self.binary_files),
            "verification": dict(self.verification),
            "promotion_state": self.promotion_state,
            "apply_state": self.apply_state,
            "promotion_request_id": self.promotion_request_id,
            "limitations": list(self.limitations),
            "tests": list(self.tests),
            "warnings": list(self.suspicious) + [
                item for item in self.limitations if item
            ],
            "summary": dict(self.summary),
            "metadata": {
                key: value
                for key, value in self.metadata.items()
                if technical or key not in {"staging_path", "gitdir"}
            },
        }
        if include_diff:
            view["diff"] = self.diff_text
        if technical:
            view["staging_path"] = self.staging_path
        return view


class StagingController:
    """Create, inspect, promote, and clean staged coding workspaces."""

    def __init__(
        self,
        store: Any | None = None,
        *,
        staging_root: Path | None = None,
        approval_store: ApprovalStore | None = None,
    ) -> None:
        self.store = store
        if staging_root is not None:
            self.staging_root = Path(staging_root).expanduser().resolve()
        elif store is not None and getattr(store, "db_path", None) is not None:
            self.staging_root = default_staging_root(Path(store.db_path).parent)
        else:
            self.staging_root = default_staging_root()
        self.approval_store = approval_store
        if self.approval_store is None and store is not None:
            db_path = getattr(store, "db_path", None)
            if db_path is not None:
                self.approval_store = ApprovalStore(Path(db_path))

    def create_workspace(
        self,
        authoritative: Path | str,
        *,
        coding_id: str | None = None,
        mission_id: str | None = None,
        execution_id: str | None = None,
        provider_id: str = "cursor",
    ) -> dict[str, Any]:
        repo = validate_repository_path(str(authoritative))
        baseline = inspect_repository(repo)
        workspace_id = _uid("ws")
        staging_path = self.staging_root / workspace_id
        self.staging_root.mkdir(parents=True, exist_ok=True)
        kind = "git_worktree" if baseline["is_git"] and baseline["head"] else "copy"
        if kind == "git_worktree":
            self._create_worktree(Path(baseline["repository_root"]), staging_path, baseline["head"])
        else:
            self._create_copy(repo, staging_path)
        record = {
            "workspace_id": workspace_id,
            "coding_id": coding_id,
            "mission_id": mission_id,
            "execution_id": execution_id,
            "authoritative_path": str(repo),
            "staging_path": str(staging_path),
            "kind": kind,
            "status": "active",
            "head": baseline["head"],
            "branch": baseline["branch"],
            "dirty_paths": list(baseline["dirty_paths"]),
            "baseline": baseline,
            "provider_id": provider_id,
            "created_at": _iso(),
            "updated_at": _iso(),
            "cleaned_at": None,
            "metadata": {
                "dirty_at_start": bool(baseline["dirty_paths"]),
                "containment": "authoritative_state_separation",
            },
        }
        if self.store is not None:
            self.store.save_staged_workspace(record)
        return record

    def generate_changeset(
        self,
        workspace: dict[str, Any],
        *,
        provider_id: str = "cursor",
        runtime: str = "cursor",
        coding_id: str | None = None,
        mission_id: str | None = None,
        execution_id: str | None = None,
        tests: list[str] | None = None,
        limitations: list[str] | None = None,
        run_verification: bool = True,
    ) -> ChangeSet:
        staging = Path(workspace["staging_path"])
        authoritative = Path(workspace["authoritative_path"])
        if workspace.get("kind") == "git_worktree":
            files, diff_text, binary_files = self._git_changes(
                staging, authoritative, starting_head=workspace.get("head")
            )
        else:
            files, diff_text, binary_files = self._copy_changes(
                Path(workspace["authoritative_path"]), staging
            )
        suspicious = [
            item.path for item in files if item.blocked or item.sensitive or item.invalid
        ]
        additions = sum(item.additions for item in files)
        deletions = sum(item.deletions for item in files)
        encoded = diff_text.encode("utf-8", errors="replace")
        diff_hash = hashlib.sha256(encoded).hexdigest()
        stored_diff = diff_text if len(diff_text) <= MAX_DIFF_CHARS else diff_text[:MAX_DIFF_CHARS]
        notes = list(limitations or [])
        if any(workspace.get("dirty_paths") or []):
            notes.append(
                "The authoritative repository had uncommitted files when staging "
                "started. Staging used HEAD and did not include or reset that dirty work."
            )
        notes.append(CONTAINMENT_LIMITATION)
        verification = (
            self.verify_staging(staging, reported_tests=tests or [])
            if run_verification
            else {"status": "skipped", "tests": list(tests or [])}
        )
        promotion_state = "pending"
        if not files:
            promotion_state = "empty"
        if any(item.blocked for item in files):
            promotion_state = "blocked"
            notes.append("ChangeSet contains path or sensitive-file policy violations")
        changeset = ChangeSet(
            changeset_id=_uid("chs"),
            workspace_id=workspace["workspace_id"],
            coding_id=coding_id or workspace.get("coding_id"),
            mission_id=mission_id or workspace.get("mission_id"),
            execution_id=execution_id or workspace.get("execution_id"),
            provider_id=provider_id,
            runtime=runtime,
            authoritative_path=str(authoritative),
            starting_head=workspace.get("head"),
            staging_path=str(staging),
            created_at=_iso(),
            updated_at=_iso(),
            files=files,
            diff_text=stored_diff,
            diff_hash=diff_hash,
            binary_files=binary_files,
            verification=verification,
            promotion_state=promotion_state,
            limitations=list(dict.fromkeys(notes)),
            tests=list(verification.get("tests") or tests or []),
            suspicious=suspicious,
            summary={
                "files_changed": len(files),
                "additions": additions,
                "deletions": deletions,
            },
            metadata={
                "workspace_kind": workspace.get("kind"),
                "dirty_at_start": bool(workspace.get("dirty_paths")),
                "branch": workspace.get("branch"),
            },
        )
        if self.store is not None:
            self.store.save_change_set(changeset.to_record())
        return changeset

    def create_promotion_request(self, changeset: ChangeSet) -> ApprovalRequest | None:
        if self.approval_store is None or changeset.promotion_state not in {"pending"}:
            return None
        if changeset.promotion_request_id:
            existing = self.approval_store.get_request(changeset.promotion_request_id)
            if existing is not None:
                return existing
        summary = changeset.summary
        headline = (
            f"Apply {summary.get('files_changed', 0)} staged "
            f"{'file' if summary.get('files_changed') == 1 else 'files'} to the repository"
        )
        request = ApprovalRequest(
            request_id=_uid("areq"),
            source_type=PROMOTION_SOURCE_TYPE,
            source_id=changeset.changeset_id,
            run_id=changeset.execution_id or changeset.changeset_id,
            goal_id=changeset.coding_id or changeset.changeset_id,
            track_id=changeset.mission_id or "coding-promotion",
            opportunity_plan_id=changeset.coding_id or "coding-promotion",
            goal_text=headline,
            track_name="Authoritative promotion",
            risk_level="red",
            metadata={
                "changeset_id": changeset.changeset_id,
                "workspace_id": changeset.workspace_id,
                "coding_id": changeset.coding_id,
                "mission_id": changeset.mission_id,
                "execution_id": changeset.execution_id,
                "provider": changeset.provider_id,
                "runtime": changeset.runtime,
                "capability_role": "coding_agent",
                "repository_path": changeset.authoritative_path,
                "action_name": "promote",
                "action_category": "authoritative_write",
                "headline": headline,
                "summary": (
                    f"{summary.get('files_changed', 0)} files changed · "
                    f"{summary.get('additions', 0)} additions · "
                    f"{summary.get('deletions', 0)} deletions"
                ),
                "policy_classification": "pending_human",
                "files_changed": [item.path for item in changeset.files],
            },
        )
        request.steps.append(
            ApprovalStep(
                step_id=_uid("astp"),
                request_id=request.request_id,
                source_type=PROMOTION_SOURCE_TYPE,
                source_id=changeset.changeset_id,
                task=headline,
                risk_level="red",
                permission_scope="write",
                approval_required=True,
                approval_state="pending",
                metadata={
                    "changeset_id": changeset.changeset_id,
                    "headline": headline,
                    "kind": "promote",
                },
            )
        )
        request.refresh_state()
        self.approval_store.save_request(request)
        changeset.promotion_request_id = request.request_id
        changeset.updated_at = _iso()
        if self.store is not None:
            self.store.save_change_set(changeset.to_record())
        return request

    def get_changeset(self, changeset_id: str) -> ChangeSet:
        if self.store is None:
            raise KeyError(changeset_id)
        record = self.store.get_change_set(changeset_id)
        if record is None:
            raise KeyError(changeset_id)
        return self._from_record(record)

    def apply_changeset(
        self,
        changeset_id: str,
        *,
        reason: str = "",
        coding_id: str | None = None,
        mission_id: str | None = None,
    ) -> ChangeSet:
        changeset = self.get_changeset(changeset_id)
        self._assert_promotion_match(changeset, coding_id=coding_id, mission_id=mission_id)
        if changeset.promotion_state == "applied":
            raise PromotionStateError("duplicate promotion")
        if changeset.promotion_state == "rejected":
            raise PromotionStateError("already rejected ChangeSet")
        if changeset.promotion_state == "blocked":
            raise PromotionBlockedError("ChangeSet is blocked by path policy")
        if changeset.promotion_state == "empty":
            raise PromotionStateError("ChangeSet has no files to apply")
        if changeset.promotion_state not in {"pending", "conflict"}:
            raise PromotionStateError(f"stale promotion state: {changeset.promotion_state}")
        conflict = self._promotion_conflict(changeset)
        if conflict:
            changeset.promotion_state = "conflict"
            changeset.apply_state = "refused"
            changeset.limitations = list(dict.fromkeys([*changeset.limitations, conflict]))
            changeset.updated_at = _iso()
            if self.store is not None:
                self.store.save_change_set(changeset.to_record())
            raise PromotionConflictError(conflict)
        self._apply_files(changeset)
        changeset.promotion_state = "applied"
        changeset.apply_state = "applied"
        changeset.updated_at = _iso()
        changeset.metadata = {
            **changeset.metadata,
            "applied_at": changeset.updated_at,
            "apply_reason": reason[:500],
        }
        self._mark_promotion_decision(changeset, decision="approved", reason=reason)
        if self.store is not None:
            self.store.save_change_set(changeset.to_record())
        self.cleanup_workspace(changeset.workspace_id, force=False)
        return changeset

    def reject_changeset(
        self,
        changeset_id: str,
        *,
        reason: str = "",
        coding_id: str | None = None,
        mission_id: str | None = None,
    ) -> ChangeSet:
        changeset = self.get_changeset(changeset_id)
        self._assert_promotion_match(changeset, coding_id=coding_id, mission_id=mission_id)
        if changeset.promotion_state == "applied":
            raise PromotionStateError("duplicate promotion")
        if changeset.promotion_state == "rejected":
            raise PromotionStateError("already rejected ChangeSet")
        changeset.promotion_state = "rejected"
        changeset.apply_state = "rejected"
        changeset.updated_at = _iso()
        changeset.metadata = {
            **changeset.metadata,
            "rejected_at": changeset.updated_at,
            "reject_reason": reason[:500],
        }
        self._mark_promotion_decision(changeset, decision="rejected", reason=reason)
        if self.store is not None:
            self.store.save_change_set(changeset.to_record())
        self.cleanup_workspace(changeset.workspace_id, force=False)
        return changeset

    def cleanup_workspace(self, workspace_id: str, *, force: bool = False) -> None:
        if self.store is None:
            return
        workspace = self.store.get_staged_workspace(workspace_id)
        if workspace is None:
            return
        pending = self.store.list_change_sets(workspace_id=workspace_id)
        if not force and any(item.get("promotion_state") == "pending" for item in pending):
            return
        path = Path(workspace["staging_path"])
        if workspace.get("kind") == "git_worktree":
            root = Path(workspace["authoritative_path"])
            if path.exists():
                _git(["worktree", "remove", "--force", str(path)], cwd=root, timeout=60)
            _git(["worktree", "prune"], cwd=root)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        workspace["status"] = "cleaned"
        workspace["cleaned_at"] = _iso()
        workspace["updated_at"] = workspace["cleaned_at"]
        self.store.save_staged_workspace(workspace)

    def cleanup_stale(self, *, max_age_hours: int = STALE_WORKSPACE_HOURS) -> int:
        if self.store is None:
            return 0
        removed = 0
        cutoff = _now().timestamp() - max(1, max_age_hours) * 3600
        for workspace in self.store.list_staged_workspaces(limit=500):
            if workspace.get("status") == "cleaned":
                continue
            pending = self.store.list_change_sets(workspace_id=workspace["workspace_id"])
            if any(item.get("promotion_state") == "pending" for item in pending):
                continue
            created = workspace.get("created_at") or ""
            try:
                stamp = datetime.fromisoformat(created).timestamp()
            except ValueError:
                stamp = 0.0
            if stamp and stamp > cutoff:
                continue
            self.cleanup_workspace(workspace["workspace_id"], force=True)
            removed += 1
        return removed

    def verify_staging(
        self,
        staging: Path,
        *,
        reported_tests: list[str] | None = None,
    ) -> dict[str, Any]:
        tests = list(reported_tests or [])
        test_files = [
            str(path.relative_to(staging))
            for path in sorted(staging.rglob("test_*.py"))
            if path.is_file() and ".venv" not in path.parts
        ]
        tests.extend(test_files)
        if not test_files:
            return {
                "status": "not_run",
                "tests": list(dict.fromkeys(tests)),
                "summary": "No test files were present in the staged workspace.",
            }
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "--tb=line",
                    "--noconftest",
                    "-c",
                    os.devnull,
                    f"--rootdir={staging}",
                ],
                cwd=str(staging),
                capture_output=True,
                text=True,
                timeout=120,
                env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "status": "failed",
                "tests": list(dict.fromkeys(tests)),
                "summary": f"Verification did not finish: {exc}"[:400],
            }
        output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        summary = output.splitlines()[-1][:400] if output else f"exit {result.returncode}"
        status = "passed" if result.returncode == 0 else "failed"
        return {
            "status": status,
            "exit_code": result.returncode,
            "tests": list(dict.fromkeys(tests)),
            "summary": summary,
        }

    def _create_worktree(self, repo: Path, staging_path: Path, head: str) -> None:
        if staging_path.exists():
            raise StagingError("staging path already exists")
        result = _git(
            ["worktree", "add", "--detach", str(staging_path), head],
            cwd=repo,
            timeout=60,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "git worktree add failed").strip()[:400]
            raise StagingError(detail)

    def _create_copy(self, repo: Path, staging_path: Path) -> None:
        def ignore(directory: str, names: list[str]) -> set[str]:
            _ = directory
            return {name for name in names if name in _COPY_IGNORE}

        shutil.copytree(repo, staging_path, ignore=ignore, symlinks=False)

    def _git_changes(
        self, staging: Path, authoritative: Path, *, starting_head: str | None
    ) -> tuple[list[FileChange], str, list[dict[str, Any]]]:
        _git(["add", "-A"], cwd=staging)
        base = ["diff", "--cached", "--find-renames", "--binary", "--no-ext-diff"]
        stat_base = ["diff", "--cached", "--find-renames", "--no-ext-diff"]
        if starting_head:
            base.append(starting_head)
            stat_base.append(starting_head)
        diff = _git(base, cwd=staging, timeout=60)
        numstat = _git([*stat_base, "--numstat"], cwd=staging)
        name_status = _git([*stat_base, "--name-status"], cwd=staging)
        files: list[FileChange] = []
        binary_files: list[dict[str, Any]] = []
        stats: dict[str, tuple[int, int, bool]] = {}
        for line in numstat.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            added_raw, deleted_raw, path = parts[0], parts[1], parts[2]
            binary = added_raw == "-" or deleted_raw == "-"
            additions = 0 if binary else int(added_raw or 0)
            deletions = 0 if binary else int(deleted_raw or 0)
            if " => " in path:
                path = path.split(" => ", 1)[1].strip(" {}")
            elif "\t" in path:
                path = path.split("\t")[-1]
            stats[path] = (additions, deletions, binary)
        for line in name_status.stdout.splitlines():
            parts = line.split("\t")
            if not parts:
                continue
            code = parts[0][:1]
            if code == "R" and len(parts) >= 3:
                old_path, path = parts[1], parts[2]
                kind = "renamed"
            elif code == "A":
                old_path, path, kind = None, parts[-1], "added"
            elif code == "D":
                old_path, path, kind = None, parts[-1], "deleted"
            else:
                old_path, path, kind = None, parts[-1], "modified"
            additions, deletions, binary = stats.get(path, (0, 0, False))
            policy = classify_path_policy(path, repository=authoritative)
            change = FileChange(
                path=path,
                kind=kind,
                old_path=old_path,
                binary=binary,
                additions=additions,
                deletions=deletions,
                blocked=bool(policy["blocked"]),
                sensitive=bool(policy["sensitive"]),
                invalid=bool(policy["invalid"]),
                reasons=list(policy["reasons"]),
            )
            files.append(change)
            if binary:
                binary_files.append({"path": path, "kind": kind})
        return files, diff.stdout, binary_files

    def _copy_changes(
        self, authoritative: Path, staging: Path
    ) -> tuple[list[FileChange], str, list[dict[str, Any]]]:
        before = _file_digest_map(authoritative)
        after = _file_digest_map(staging)
        files: list[FileChange] = []
        binary_files: list[dict[str, Any]] = []
        diff_lines: list[str] = []
        for relative in sorted(set(before) | set(after)):
            if before.get(relative) == after.get(relative):
                continue
            if relative not in before:
                kind = "added"
            elif relative not in after:
                kind = "deleted"
            else:
                kind = "modified"
            policy = classify_path_policy(relative, repository=authoritative)
            binary = _looks_binary(staging / relative if kind != "deleted" else authoritative / relative)
            additions, deletions, snippet = _text_diff(
                authoritative / relative if kind != "added" else None,
                staging / relative if kind != "deleted" else None,
                relative,
            )
            files.append(
                FileChange(
                    path=relative,
                    kind=kind,
                    binary=binary,
                    additions=additions,
                    deletions=deletions,
                    blocked=bool(policy["blocked"]),
                    sensitive=bool(policy["sensitive"]),
                    invalid=bool(policy["invalid"]),
                    reasons=list(policy["reasons"]),
                )
            )
            if binary:
                binary_files.append({"path": relative, "kind": kind})
            else:
                diff_lines.append(snippet)
        return files, "\n".join(diff_lines), binary_files

    def _promotion_conflict(self, changeset: ChangeSet) -> str | None:
        authoritative = Path(changeset.authoritative_path)
        if not authoritative.exists():
            return "authoritative repository no longer exists"
        current = inspect_repository(authoritative)
        if changeset.starting_head and current.get("head") != changeset.starting_head:
            return "Repository changed since this task started"
        changed_paths = {item.path for item in changeset.files}
        for item in changeset.files:
            if item.old_path:
                changed_paths.add(item.old_path)
        overlap = sorted(set(current.get("dirty_paths") or []) & changed_paths)
        if overlap:
            return (
                "Authoritative repository has uncommitted edits that overlap "
                "this ChangeSet: " + ", ".join(overlap[:12])
            )
        for item in changeset.files:
            policy = classify_path_policy(item.path, repository=authoritative)
            if policy["blocked"]:
                return f"path policy blocked {item.path}"
        staging = Path(changeset.staging_path)
        if not staging.exists():
            return "staged workspace is no longer available for inspection or apply"
        return None

    def _apply_files(self, changeset: ChangeSet) -> None:
        authoritative = Path(changeset.authoritative_path).resolve()
        staging = Path(changeset.staging_path).resolve()
        for item in changeset.files:
            destination = _safe_repo_path(authoritative, item.path)
            if item.kind == "deleted":
                if destination.is_file() or destination.is_symlink():
                    destination.unlink()
                continue
            source_rel = item.path
            source = _safe_repo_path(staging, source_rel)
            if item.kind == "renamed" and item.old_path:
                old = _safe_repo_path(authoritative, item.old_path)
                if old.exists() and old.is_file():
                    old.unlink()
            if not source.exists() or not source.is_file():
                raise PromotionBlockedError(f"staged file missing: {item.path}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            _clear_write_if_needed(destination)

    def _assert_promotion_match(
        self,
        changeset: ChangeSet,
        *,
        coding_id: str | None,
        mission_id: str | None,
    ) -> None:
        if coding_id and changeset.coding_id and coding_id != changeset.coding_id:
            raise PromotionStateError("cross-Mission promotion")
        if mission_id and changeset.mission_id and mission_id != changeset.mission_id:
            raise PromotionStateError("cross-Mission promotion")

    def _mark_promotion_decision(
        self,
        changeset: ChangeSet,
        *,
        decision: str,
        reason: str,
    ) -> None:
        if self.approval_store is None or not changeset.promotion_request_id:
            return
        request = self.approval_store.get_request(changeset.promotion_request_id)
        if request is None or not request.steps:
            return
        step = request.steps[0]
        if step.approval_state not in {"pending"}:
            return
        step.approval_state = "approved" if decision == "approved" else "rejected"
        step.updated_at = _iso()
        request.metadata = {
            **request.metadata,
            "decision_source": "human",
            "decision_kind": "apply" if decision == "approved" else "reject",
            "decision_reason": reason[:500],
        }
        request.refresh_state()
        self.approval_store.save_request(request)

    @staticmethod
    def _from_record(record: dict[str, Any]) -> ChangeSet:
        allowed = {
            "path",
            "kind",
            "old_path",
            "binary",
            "additions",
            "deletions",
            "blocked",
            "sensitive",
            "invalid",
            "reasons",
        }
        files = []
        for item in record.get("files") or []:
            if isinstance(item, FileChange):
                files.append(item)
                continue
            files.append(FileChange(**{key: item[key] for key in allowed if key in item}))
        return ChangeSet(
            changeset_id=record["changeset_id"],
            workspace_id=record["workspace_id"],
            coding_id=record.get("coding_id"),
            mission_id=record.get("mission_id"),
            execution_id=record.get("execution_id"),
            provider_id=record.get("provider_id") or "",
            runtime=record.get("runtime") or "",
            authoritative_path=record["authoritative_path"],
            starting_head=record.get("starting_head"),
            staging_path=record["staging_path"],
            created_at=record["created_at"],
            files=files,
            diff_text=record.get("diff_text") or "",
            diff_hash=record.get("diff_hash") or "",
            binary_files=list(record.get("binary_files") or []),
            verification=dict(record.get("verification") or {}),
            promotion_state=record.get("promotion_state") or "pending",
            apply_state=record.get("apply_state"),
            promotion_request_id=record.get("promotion_request_id"),
            limitations=list(record.get("limitations") or []),
            tests=list(record.get("tests") or []),
            suspicious=list(record.get("suspicious") or []),
            summary=dict(record.get("summary") or {}),
            metadata=dict(record.get("metadata") or {}),
            updated_at=record.get("updated_at") or record["created_at"],
        )


def _safe_repo_path(root: Path, relative: str) -> Path:
    policy = classify_path_policy(relative, repository=root)
    if policy["invalid"] or policy["blocked"]:
        raise PromotionBlockedError(
            f"refusing path {relative}: {', '.join(policy['reasons']) or 'blocked'}"
        )
    candidate = (root / relative).resolve()
    if candidate != root.resolve() and not candidate.is_relative_to(root.resolve()):
        raise PromotionBlockedError(f"path escapes repository: {relative}")
    return candidate


def _file_digest_map(root: Path, *, limit: int = 2000) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    if not root.exists():
        return snapshot
    for path in sorted(root.rglob("*")):
        if len(snapshot) >= limit:
            break
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in _COPY_IGNORE for part in relative.parts):
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
        snapshot[str(relative)] = digest
    return snapshot


def _looks_binary(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        sample = path.read_bytes()[:8000]
    except OSError:
        return True
    return b"\x00" in sample


def _text_diff(before: Path | None, after: Path | None, relative: str) -> tuple[int, int, str]:
    old = _read_text(before)
    new = _read_text(after)
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    additions = sum(1 for line in new_lines if line not in old_lines)
    deletions = sum(1 for line in old_lines if line not in new_lines)
    snippet = "\n".join(
        [
            f"--- a/{relative}",
            f"+++ b/{relative}",
            *[f"-{line}" for line in old_lines[:40]],
            *[f"+{line}" for line in new_lines[:40]],
        ]
    )
    return additions, deletions, snippet


def _read_text(path: Path | None) -> str:
    if path is None or not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _clear_write_if_needed(path: Path) -> None:
    try:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IWUSR)
    except OSError:
        return


def authoritative_unchanged(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return (
        before.get("head") == after.get("head")
        and before.get("dirty_paths") == after.get("dirty_paths")
    )
