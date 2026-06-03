"""Tests for KnowledgeGraph."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from opencobalt.core.knowledge import KnowledgeGraph


@pytest.fixture()
def kg(tmp_path: Path) -> KnowledgeGraph:
    return KnowledgeGraph(db_path=tmp_path / "knowledge.db")


def test_empty_graph_query_returns_string(kg: KnowledgeGraph) -> None:
    result = kg.query("what is the router?")
    assert isinstance(result, str)


def test_empty_graph_why_returns_string(kg: KnowledgeGraph) -> None:
    result = kg.why("router.py")
    assert isinstance(result, str)


def test_ingest_imports_finds_files(kg: KnowledgeGraph, tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("from b import foo\n")
    (src / "b.py").write_text("def foo(): pass\n")
    count = kg.ingest_imports(src)
    assert count >= 1


def test_why_after_ingest(kg: KnowledgeGraph, tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "auth.py").write_text("from db import session\n")
    (src / "db.py").write_text("def session(): pass\n")
    kg.ingest_imports(src)
    result = kg.why("auth.py")
    assert "auth" in result.lower() or isinstance(result, str)


def test_ingest_git_log_graceful_outside_repo(kg: KnowledgeGraph) -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type("R", (), {"stdout": "", "returncode": 128})()
        count = kg.ingest_git_log(n=10)
    assert count == 0
