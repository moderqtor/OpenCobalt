"""Safe subprocess runner for Receipt-Backed Execution v0.

Argv lists only, never shell strings; the shell is never enabled. Output
is captured directly into artifact files, with only bounded redacted previews
stored inline. Environment variables are never logged or dumped.
"""

from __future__ import annotations

import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from .models import ExecutionResult

PREVIEW_CHARS = 2000

_DEFAULT_ARTIFACT_DIR = Path(".opencobalt") / "artifacts"
_REDACTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|API[_-]?KEY|PASSWORD|CREDENTIAL|COOKIE|PRIVATE[_-]?KEY|SSH[_-]?KEY)[A-Z0-9_]*)\s*=\s*([^\s]+)"
        ),
        r"\1=<redacted>",
    ),
    (
        re.compile(r"(?i)\b(sk-[A-Za-z0-9_-]{8,}|ocb_[A-Za-z0-9_-]{8,})\b"),
        "<redacted>",
    ),
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "-----BEGIN PRIVATE KEY-----<redacted>-----END PRIVATE KEY-----",
    ),
)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class ProcessRunner:
    """Runs one argv command and returns a structured ExecutionResult."""

    def __init__(
        self,
        *,
        artifact_dir: Path | None = None,
        preview_chars: int = PREVIEW_CHARS,
    ) -> None:
        self.artifact_dir = (artifact_dir or _DEFAULT_ARTIFACT_DIR).expanduser()
        self.preview_chars = preview_chars

    def run(
        self,
        argv: list[str],
        *,
        plan_id: str,
        step_id: str | None = None,
        runtime: str = "unknown",
        cwd: str | None = None,
        timeout_seconds: int = 120,
    ) -> ExecutionResult:
        if not argv or not isinstance(argv, list) or not all(isinstance(part, str) for part in argv):
            raise ValueError("argv must be a non-empty list of strings")

        started = _now()
        t0 = time.monotonic()
        result = ExecutionResult(
            plan_id=plan_id,
            step_id=step_id,
            runtime=runtime,
            command_argv=list(argv),
            cwd=cwd,
            started_at=started,
        )
        stdout_path, stderr_path = self._output_paths(result.execution_id)

        try:
            with stdout_path.open("w+", encoding="utf-8") as stdout_file, stderr_path.open(
                "w+", encoding="utf-8"
            ) as stderr_file:
                completed = subprocess.run(
                    argv,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    text=True,
                    cwd=cwd,
                    timeout=timeout_seconds,
                )
            result.return_code = completed.returncode
            result.status = "succeeded" if completed.returncode == 0 else "failed"
            if completed.returncode != 0:
                result.error = f"exit code {completed.returncode}"
        except FileNotFoundError:
            result.status = "failed"
            result.error = f"executable not found: {argv[0]}"
        except subprocess.TimeoutExpired:
            result.status = "timeout"
            result.error = f"timed out after {timeout_seconds}s"
        except OSError as exc:
            result.status = "failed"
            result.error = f"os error: {exc}"

        result.finished_at = _now()
        result.duration_ms = int((time.monotonic() - t0) * 1000)
        result.stdout_preview = self._preview(stdout_path)
        result.stderr_preview = self._preview(stderr_path)
        result.stdout_path = self._path_if_nonempty(stdout_path)
        result.stderr_path = self._path_if_nonempty(stderr_path)
        return result

    def _output_paths(self, execution_id: str) -> tuple[Path, Path]:
        out_dir = self.artifact_dir / execution_id
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir / "stdout.log", out_dir / "stderr.log"

    def _preview(self, path: Path) -> str:
        if not path.exists() or path.stat().st_size == 0:
            return ""
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return redact_text(_read_bounded(handle, self.preview_chars))

    def _path_if_nonempty(self, path: Path) -> str | None:
        if not path.exists() or path.stat().st_size == 0:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return None
        return str(path)


def _read_bounded(handle: TextIO, limit: int) -> str:
    return handle.read(max(limit, 0))


def redact_text(text: str) -> str:
    """Redact obvious credential-shaped values before previewing/logging text."""
    redacted = text
    for pattern, replacement in _REDACTION_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_argv(argv: list[str]) -> list[str]:
    return [redact_text(part) for part in argv]
