"""Shared pytest fixtures for OpenCobalt tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from opencobalt.core.ledger import Ledger


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Return a path to a fresh, isolated SQLite ledger database."""
    return tmp_path / "ledger.db"


@pytest.fixture
def ledger(db_path: Path) -> Ledger:
    """Return a fresh Ledger backed by a temporary database."""
    return Ledger(db_path)
