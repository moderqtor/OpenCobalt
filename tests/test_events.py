import json
import tempfile
from pathlib import Path

from opencobalt.core.events import append_event, make_event, read_events


def test_make_event_required_fields():
    e = make_event(
        event_type="session_start",
        subject_type="session",
        subject_id="s-001",
        message="started",
    )
    assert e["id"].startswith("evt-")
    assert e["event_type"] == "session_start"
    assert e["message"] == "started"
    assert e["version"] == 1


def test_make_event_metadata_defaults_empty():
    e = make_event(event_type="t", subject_type="s", subject_id="x", message="m")
    assert e["metadata"] == {}


def test_make_event_tool_field():
    e = make_event(event_type="t", subject_type="s", subject_id="x", message="m", tool="pytest")
    assert e["tool"] == "pytest"


def test_append_and_read_single_event():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = Path(f.name)
    e = make_event(event_type="test", subject_type="run", subject_id="r1", message="hello")
    append_event(e, path=path)
    events = read_events(path=path)
    assert len(events) == 1
    assert events[0]["event_type"] == "test"
    assert events[0]["message"] == "hello"


def test_append_multiple_events():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = Path(f.name)
    for i in range(3):
        e = make_event(event_type=f"evt_{i}", subject_type="s", subject_id=str(i), message=str(i))
        append_event(e, path=path)
    events = read_events(path=path)
    assert len(events) == 3


def test_read_events_empty_file():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = Path(f.name)
    events = read_events(path=path)
    assert events == []


def test_read_events_missing_file():
    events = read_events(path=Path("/tmp/does-not-exist-opencobalt.jsonl"))
    assert events == []


def test_read_events_respects_limit():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = Path(f.name)
    for i in range(10):
        e = make_event(event_type="t", subject_type="s", subject_id=str(i), message=str(i))
        append_event(e, path=path)
    events = read_events(path=path, limit=3)
    assert len(events) == 3


def test_append_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "dir" / "events.jsonl"
    e = make_event(event_type="t", subject_type="s", subject_id="x", message="m")
    append_event(e, path=path)
    assert path.exists()
