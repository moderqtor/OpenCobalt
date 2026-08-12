"""Safe subprocess runner for Receipt-Backed Execution v0.

Argv lists only, never shell strings; the shell is never enabled. Output
is captured directly into artifact files, with only bounded redacted previews
stored inline. Environment variables are never logged or dumped.
"""

from __future__ import annotations

import json
import os
import re
import select
import subprocess
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

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


class InteractiveSession:
    """Line-oriented stdio session owned by ProcessRunner.interact."""

    def __init__(
        self,
        proc: subprocess.Popen[bytes],
        *,
        deadline: float,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self._proc = proc
        self._deadline = deadline
        self._cancel_check = cancel_check
        self._rx = b""

    @property
    def cancelled(self) -> bool:
        return bool(self._cancel_check and self._cancel_check())

    def remaining_seconds(self) -> float:
        return max(0.0, self._deadline - time.monotonic())

    def write_message(self, payload: dict[str, Any]) -> None:
        if self._proc.stdin is None:
            raise RuntimeError("interactive session stdin is closed")
        line = json.dumps(payload, separators=(",", ":")) + "\n"
        raw = self._proc.stdin
        if "b" in getattr(raw, "mode", "b"):
            raw.write(line.encode("utf-8"))
        else:
            raw.write(line)
        raw.flush()

    def read_message(self, timeout: float | None = None) -> dict[str, Any] | None:
        if self._proc.stdout is None:
            return None
        wait = self.remaining_seconds() if timeout is None else min(timeout, self.remaining_seconds())
        if wait <= 0:
            raise TimeoutError("interactive session timed out")
        if self.cancelled:
            return None
        stdout = self._proc.stdout
        fileno = stdout.fileno()
        binary = "b" in getattr(stdout, "mode", "b")
        while True:
            if binary and b"\n" in self._rx:
                raw_line, self._rx = self._rx.split(b"\n", 1)
                line = raw_line.decode("utf-8", errors="replace").strip()
                break
            wait = self.remaining_seconds() if timeout is None else min(timeout, self.remaining_seconds())
            if wait <= 0:
                raise TimeoutError("interactive session timed out")
            ready, _, _ = select.select([fileno], [], [], wait)
            if not ready:
                if self.remaining_seconds() <= 0:
                    raise TimeoutError("interactive session timed out")
                return None
            if binary:
                chunk = os.read(fileno, 65536)
                if not chunk:
                    if not self._rx:
                        return None
                    line = self._rx.decode("utf-8", errors="replace").strip()
                    self._rx = b""
                    break
                self._rx += chunk
                continue
            line = stdout.readline().strip()
            break
        if not line:
            return None
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed ACP JSON: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValueError("malformed ACP JSON: expected an object")
        return payload

    def close_stdin(self) -> None:
        if self._proc.stdin is not None and not self._proc.stdin.closed:
            try:
                self._proc.stdin.close()
            except OSError:
                pass


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

    def interact(
        self,
        argv: list[str],
        *,
        plan_id: str,
        handler: Callable[[InteractiveSession], dict[str, Any] | None],
        step_id: str | None = None,
        runtime: str = "unknown",
        cwd: str | None = None,
        timeout_seconds: int = 120,
        cancel_check: Callable[[], bool] | None = None,
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
        proc: subprocess.Popen[bytes] | None = None
        payload: dict[str, Any] | None = None
        try:
            with stderr_path.open("w+", encoding="utf-8") as stderr_file:
                proc = subprocess.Popen(
                    argv,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=stderr_file,
                    bufsize=0,
                    cwd=cwd,
                    start_new_session=True,
                )
                session = InteractiveSession(
                    proc,
                    deadline=t0 + timeout_seconds,
                    cancel_check=cancel_check,
                )
                payload = handler(session) or {}
                session.close_stdin()
                try:
                    proc.wait(timeout=min(5, max(1, int(session.remaining_seconds()) or 1)))
                except subprocess.TimeoutExpired:
                    _terminate_process(proc)
                    proc.wait(timeout=5)
            result.return_code = proc.returncode
            if cancel_check and cancel_check():
                result.status = "failed"
                result.error = "cancelled"
            elif result.return_code not in {0, None}:
                result.status = "failed"
                result.error = f"exit code {result.return_code}"
            else:
                result.status = "succeeded"
        except FileNotFoundError:
            result.status = "failed"
            result.error = f"executable not found: {argv[0]}"
        except TimeoutError as exc:
            result.status = "timeout"
            result.error = str(exc)
            if proc is not None:
                _terminate_process(proc)
        except ValueError as exc:
            result.status = "failed"
            result.error = str(exc)
            if proc is not None:
                _terminate_process(proc)
        except OSError as exc:
            result.status = "failed"
            result.error = f"os error: {exc}"
            if proc is not None:
                _terminate_process(proc)
        finally:
            if proc is not None and proc.poll() is None:
                _terminate_process(proc)

        envelope = payload if isinstance(payload, dict) else {}
        stdout_path.write_text(
            json.dumps(envelope, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
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


def _terminate_process(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    try:
        if proc.pid:
            os.killpg(proc.pid, 15)
    except (OSError, ProcessLookupError):
        proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            if proc.pid:
                os.killpg(proc.pid, 9)
        except (OSError, ProcessLookupError):
            proc.kill()
