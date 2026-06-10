"""Optional sleep prevention for long-running execution sessions.

On macOS, `keep_awake(True)` starts a scoped `caffeinate` child process that
prevents idle sleep while a run is in progress. The child is started with
`-w <our pid>` so it can never outlive OpenCobalt, and it is terminated
explicitly when the context exits, including on timeout or failure.

This is UX support only: it never changes policy gates, approval rules, or
model behavior, and it is never enabled by default. On non-macOS platforms,
or when the `caffeinate` utility is missing, it is a silent no-op.
"""

from __future__ import annotations

import contextlib
import os
import platform
import shutil
import subprocess
from collections.abc import Generator

_CAFFEINATE_BIN = "caffeinate"
# -d: prevent display sleep, -i: prevent idle sleep, -m: prevent disk sleep,
# -s: prevent system sleep on AC power
_CAFFEINATE_ARGS = ("-dims",)


def caffeinate_available() -> bool:
    """True when the platform supports scoped sleep prevention."""
    return platform.system() == "Darwin" and shutil.which(_CAFFEINATE_BIN) is not None


@contextlib.contextmanager
def keep_awake(enabled: bool = False) -> Generator[bool]:
    """Hold the machine awake while the context is active.

    Yields True when a caffeinate process is actually running, False when
    disabled or unsupported. Cleanup always terminates the child; the
    `-w <pid>` tie to our process id is the backstop if cleanup never runs.
    """
    if not enabled or not caffeinate_available():
        yield False
        return

    proc: subprocess.Popen[bytes] | None = None
    try:
        proc = subprocess.Popen(
            [_CAFFEINATE_BIN, *_CAFFEINATE_ARGS, "-w", str(os.getpid())],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        yield False
        return

    try:
        yield True
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
