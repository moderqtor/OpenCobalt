"""Tests for verify_async."""

from __future__ import annotations

import time
from pathlib import Path

from opencobalt.core.background import BackgroundRunner
from opencobalt.core.ledger import Ledger
from opencobalt.core.verify import verify_async


def test_verify_async_queues_result(tmp_path: Path) -> None:
    runner = BackgroundRunner()
    ledger = Ledger(tmp_path / "ledger.db")
    # Point root at tmp_path (empty dir) so pytest exits 5 (no tests found) -- fast, no recursion.
    verify_async(runner, root=tmp_path, ledger=ledger)
    time.sleep(3)
    results = runner.drain()
    runner.shutdown()
    assert len(results) >= 1
    assert "VERIFIED" in results[0].output or "FAILED" in results[0].output
