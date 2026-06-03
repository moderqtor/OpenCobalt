"""Thread-based background task runner for the cobalt shell."""

from __future__ import annotations

import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class BackgroundResult:
    task_id: str
    output: str
    error: str | None = None
    elapsed_s: float = 0.0
    metadata: dict = field(default_factory=dict)


class BackgroundRunner:
    """Run callables in background threads; drain results non-blockingly."""

    def __init__(self, max_workers: int = 3) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._results: queue.Queue[BackgroundResult] = queue.Queue()
        self._lock = threading.Lock()

    def submit(self, task_id: str, fn: Callable[..., Any], *args: Any) -> None:
        """Enqueue fn(*args) to run in a background thread."""
        import time

        def _run() -> None:
            t0 = time.monotonic()
            try:
                output = fn(*args)
                elapsed = time.monotonic() - t0
                self._results.put(
                    BackgroundResult(
                        task_id=task_id,
                        output=str(output) if output is not None else "",
                        elapsed_s=round(elapsed, 2),
                    )
                )
            except Exception as exc:
                elapsed = time.monotonic() - t0
                self._results.put(
                    BackgroundResult(
                        task_id=task_id,
                        output="",
                        error=str(exc),
                        elapsed_s=round(elapsed, 2),
                    )
                )

        with self._lock:
            self._executor.submit(_run)

    def drain(self) -> list[BackgroundResult]:
        """Return all completed results without blocking."""
        results = []
        while True:
            try:
                results.append(self._results.get_nowait())
            except queue.Empty:
                break
        return results

    def shutdown(self) -> None:
        """Shut down the executor cleanly."""
        self._executor.shutdown(wait=False, cancel_futures=True)
