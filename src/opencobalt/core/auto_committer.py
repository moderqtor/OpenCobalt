"""AutoCommitter: stage artifacts and create convergence commit."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_CO_AUTHOR = "Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
_SKIP_DIRS = {"__pycache__", ".opencobalt"}
_SKIP_SUFFIXES = {".db", ".pyc"}


@dataclass
class CommitResult:
    sha: str
    files_staged: list[str] = field(default_factory=list)
    message: str = ""
    pushed: bool = False


def _should_skip_path(path: str) -> bool:
    p = Path(path)
    if any(part in _SKIP_DIRS for part in p.parts):
        return True
    if p.name == ".env" or p.name.startswith(".env."):
        return True
    return p.suffix in _SKIP_SUFFIXES


def _default_run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


class AutoCommitter:
    def __init__(
        self,
        repo_path: Path | None = None,
        run_git: Callable[[list[str], Path], subprocess.CompletedProcess] | None = None,
        push_on_converge: bool = False,
    ) -> None:
        self._repo_path = repo_path or Path(".")
        self._run_git = run_git or _default_run_git
        self._push_on_converge = push_on_converge

    def _fallback_files(self) -> list[str]:
        changed = self._run_git(["git", "diff", "--name-only", "HEAD"], self._repo_path)
        untracked = self._run_git(
            ["git", "ls-files", "--others", "--exclude-standard"],
            self._repo_path,
        )
        candidates = changed.stdout.strip().splitlines()
        candidates.extend(untracked.stdout.strip().splitlines())
        seen: set[str] = set()
        stageable: list[str] = []
        for line in candidates:
            if not line or line in seen or _should_skip_path(line):
                continue
            seen.add(line)
            stageable.append(line)
        return stageable

    def _build_message(
        self,
        session_id: str,
        seed_task: str,
        agents: list[str],
        waves: int,
        retries: int,
        tests_info: str,
        verifier_info: str,
    ) -> str:
        agents_str = ", ".join(agents) if agents else "none"
        return "\n".join([
            f"feat(converge): {seed_task[:60]}",
            "",
            f"Convergence session {session_id}",
            f"Agents: {agents_str}",
            f"Waves: {waves}, Retries: {retries}",
            f"Tests: {tests_info}",
            f"Verifier: {verifier_info}",
            "",
            _CO_AUTHOR,
        ])

    def commit(
        self,
        session_id: str,
        seed_task: str,
        artifact_paths: list[str],
        artifact_lines: list[str],
        waves: int,
        retries: int,
        agents: list[str],
        tests_info: str,
        verifier_info: str,
    ) -> CommitResult:
        if artifact_paths:
            stageable = [p for p in artifact_paths if not _should_skip_path(p)]
        else:
            stageable = self._fallback_files()

        if not stageable:
            return CommitResult(sha="", files_staged=[])

        for path in stageable:
            add_result = self._run_git(["git", "add", path], self._repo_path)
            if add_result.returncode != 0:
                return CommitResult(sha="", files_staged=stageable)

        message = self._build_message(
            session_id=session_id,
            seed_task=seed_task,
            agents=agents,
            waves=waves,
            retries=retries,
            tests_info=tests_info,
            verifier_info=verifier_info,
        )
        commit_result = self._run_git(["git", "commit", "-m", message], self._repo_path)
        if commit_result.returncode != 0:
            return CommitResult(sha="", files_staged=stageable, message=message)

        sha_result = self._run_git(["git", "rev-parse", "HEAD"], self._repo_path)
        if sha_result.returncode != 0:
            return CommitResult(sha="", files_staged=stageable, message=message)
        sha = sha_result.stdout.strip()[:8]

        pushed = False
        if self._push_on_converge:
            push_result = self._run_git(["git", "push"], self._repo_path)
            pushed = push_result.returncode == 0

        return CommitResult(sha=sha, files_staged=stageable, message=message, pushed=pushed)
