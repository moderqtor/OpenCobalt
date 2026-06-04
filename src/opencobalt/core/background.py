"""Thread-based background task runner for the cobalt shell."""

from __future__ import annotations

import queue
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
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


def _run_pytest() -> str:
    result = subprocess.run(
        ["python3", "-m", "pytest", "-q", "--tb=short"],
        capture_output=True,
        text=True,
    )
    return result.stdout


def _collect_mtimes(src_dir: Path) -> dict[Path, float]:
    return {
        p: p.stat().st_mtime
        for p in src_dir.rglob("*.py")
        if p.is_file()
    }


try:
    from watchdog.events import FileSystemEventHandler as _FSH
    from watchdog.observers import Observer

    class _WatchdogHandler(_FSH):
        def __init__(self, callback: Callable[[], None]) -> None:
            super().__init__()
            self._callback = callback

        def on_modified(self, event) -> None:
            if not event.is_directory and event.src_path.endswith(".py"):
                self._callback()

        def on_created(self, event) -> None:
            if not event.is_directory and event.src_path.endswith(".py"):
                self._callback()

    _WATCHDOG = True
except ImportError:
    _WATCHDOG = False


class TestWatcher:
    """Watch src/ and tests/ for .py changes and queue pytest via BackgroundRunner."""

    __test__ = False  # prevent pytest collection

    def __init__(
        self,
        runner: BackgroundRunner,
        src_dir: Path = Path("src"),
        interval_s: int = 10,
    ) -> None:
        self._runner = runner
        self._src_dir = src_dir
        self._interval_s = interval_s
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if _WATCHDOG:
            self._start_watchdog()
        else:
            self._start_polling()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval_s + 2)

    def _trigger(self) -> None:
        self._runner.submit("test-watch", _run_pytest)

    def _start_watchdog(self) -> None:
        handler = _WatchdogHandler(self._trigger)
        observer = Observer()
        observer.schedule(handler, str(self._src_dir), recursive=True)
        observer.start()

        def _stopper() -> None:
            self._stop_event.wait()
            observer.stop()
            observer.join()

        self._thread = threading.Thread(target=_stopper, daemon=True)
        self._thread.start()

    def _start_polling(self) -> None:
        def _poll() -> None:
            baseline = _collect_mtimes(self._src_dir)
            while not self._stop_event.wait(self._interval_s):
                current = _collect_mtimes(self._src_dir)
                if current != baseline:
                    baseline = current
                    self._trigger()

        self._thread = threading.Thread(target=_poll, daemon=True)
        self._thread.start()
