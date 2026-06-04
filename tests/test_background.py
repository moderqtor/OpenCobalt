"""Tests for BackgroundRunner."""

from __future__ import annotations

import time
from pathlib import Path

from opencobalt.core.background import BackgroundRunner, TestWatcher


def test_submit_and_drain():
    runner = BackgroundRunner(max_workers=2)
    runner.submit("t1", lambda: "hello world")
    time.sleep(0.2)
    results = runner.drain()
    runner.shutdown()
    assert len(results) == 1
    assert results[0].task_id == "t1"
    assert results[0].output == "hello world"
    assert results[0].error is None


def test_drain_is_nonblocking():
    runner = BackgroundRunner(max_workers=2)
    results = runner.drain()
    runner.shutdown()
    assert results == []


def test_error_captured_not_raised():
    def bad():
        raise ValueError("boom")

    runner = BackgroundRunner(max_workers=1)
    runner.submit("t2", bad)
    time.sleep(0.2)
    results = runner.drain()
    runner.shutdown()
    assert len(results) == 1
    assert results[0].error == "boom"
    assert results[0].output == ""


def test_multiple_tasks_all_drain():
    runner = BackgroundRunner(max_workers=3)
    for i in range(3):
        runner.submit(f"task-{i}", lambda i=i: f"result-{i}")
    time.sleep(0.3)
    results = runner.drain()
    runner.shutdown()
    assert len(results) == 3


def test_shutdown_is_safe_when_idle():
    runner = BackgroundRunner()
    runner.shutdown()


def test_test_watcher_starts_and_stops(tmp_path: Path) -> None:
    runner = BackgroundRunner()
    watcher = TestWatcher(runner, src_dir=tmp_path, interval_s=1)
    watcher.start()
    time.sleep(0.1)
    watcher.stop()
    runner.shutdown()
