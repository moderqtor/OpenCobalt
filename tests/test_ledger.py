import tempfile
from pathlib import Path

from opencobalt.core.ledger import Ledger
from opencobalt.core.models import MemoryRecord, RouteDecision, SessionEvent, VerificationResult


def _temp_ledger() -> Ledger:
    tmp = tempfile.mkdtemp()
    return Ledger(Path(tmp) / "test.db")


def test_ledger_creates_db_file():
    ledger = _temp_ledger()
    assert ledger.db_path.exists()


def test_ledger_init_idempotent():
    tmp = tempfile.mkdtemp()
    path = Path(tmp) / "test.db"
    Ledger(path)
    Ledger(path)  # second init must not raise


def test_insert_and_list_events():
    ledger = _temp_ledger()
    event = SessionEvent(project="test", source="cli", event_type="start", summary="hello")
    ledger.insert_event(event)
    events = ledger.list_events(limit=10)
    assert len(events) == 1
    assert events[0].event_type == "start"
    assert events[0].summary == "hello"


def test_insert_ignores_duplicate_id():
    ledger = _temp_ledger()
    event = SessionEvent(project="test", source="cli", event_type="start", summary="hello")
    ledger.insert_event(event)
    ledger.insert_event(event)  # same id, must not raise
    assert ledger.count_events() == 1


def test_count_events_empty():
    ledger = _temp_ledger()
    assert ledger.count_events() == 0


def test_list_events_by_project():
    ledger = _temp_ledger()
    ledger.insert_event(SessionEvent(project="a", source="cli", event_type="t", summary="s"))
    ledger.insert_event(SessionEvent(project="b", source="cli", event_type="t", summary="s"))
    assert len(ledger.list_events(project="a")) == 1
    assert len(ledger.list_events(project="b")) == 1


def test_insert_and_list_verification_results():
    ledger = _temp_ledger()
    vr = VerificationResult(command="pytest", exit_code=0, passed=True, output_summary="5 passed")
    ledger.insert_verification_result(vr)
    results = ledger.list_verification_results(limit=5)
    assert len(results) == 1
    assert results[0].passed is True
    assert results[0].command == "pytest"


def test_insert_and_list_memory_records():
    ledger = _temp_ledger()
    mr = MemoryRecord(project="proj", namespace="ideas", content="a thought", source="cli")
    ledger.insert_memory_record(mr)
    records = ledger.list_memory_records(project="proj")
    assert len(records) == 1
    assert records[0].content == "a thought"


def test_count_memory_records():
    ledger = _temp_ledger()
    assert ledger.count_memory_records() == 0
    ledger.insert_memory_record(
        MemoryRecord(project="p", namespace="n", content="c", source="cli")
    )
    assert ledger.count_memory_records() == 1


def test_insert_route_decision():
    ledger = _temp_ledger()
    rd = RouteDecision(
        task="write tests",
        recommended_tool="codex-cli",
        score=75,
        reasoning="matched test keyword",
        tier="manager",
    )
    ledger.insert_route_decision(rd)
