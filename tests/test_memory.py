import tempfile
from pathlib import Path

from opencobalt.core.ledger import Ledger
from opencobalt.core.memory import MemoryStore


def _store() -> MemoryStore:
    tmp = tempfile.mkdtemp()
    return MemoryStore(Ledger(Path(tmp) / "test.db"))


def test_write_and_read_memory():
    store = _store()
    store.write("proj", "ideas", "First idea", source="cli")
    records = store.read("proj")
    assert len(records) == 1
    assert records[0].content == "First idea"
    assert records[0].namespace == "ideas"


def test_read_by_namespace():
    store = _store()
    store.write("proj", "ideas", "idea", source="cli")
    store.write("proj", "notes", "note", source="cli")
    ideas = store.read("proj", namespace="ideas")
    notes = store.read("proj", namespace="notes")
    assert len(ideas) == 1
    assert len(notes) == 1


def test_read_returns_empty_for_unknown_project():
    store = _store()
    records = store.read("nonexistent")
    assert records == []


def test_export_markdown_creates_file(tmp_path):
    store = _store()
    store.write("proj", "ideas", "Great thought", source="cli")
    out = tmp_path / "export.md"
    store.export_markdown("proj", out)
    assert out.exists()
    text = out.read_text()
    assert "Great thought" in text
    assert "ideas" in text


def test_export_markdown_empty_project(tmp_path):
    store = _store()
    out = tmp_path / "empty.md"
    store.export_markdown("nobody", out)
    assert out.exists()
    assert "Records: 0" in out.read_text()
