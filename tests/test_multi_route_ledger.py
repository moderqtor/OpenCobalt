import pytest

from opencobalt.core.ledger import Ledger
from opencobalt.core.models import MultiRouteDecision, SubTask


@pytest.fixture
def ledger(tmp_path):
    return Ledger(db_path=tmp_path / "test.db")


def _make_decision():
    st = SubTask(task_type="impl", prompt="build it", preferred_tool="claude-code")
    return MultiRouteDecision(
        task="implement auth",
        subtasks=[st],
        tools_used=["claude-code"],
        result_id="abc123",
    )


def test_insert_multi_route_decision(ledger):
    d = _make_decision()
    ledger.insert_multi_route_decision(d)


def test_list_multi_route_decisions_returns_inserted(ledger):
    d = _make_decision()
    ledger.insert_multi_route_decision(d)
    results = ledger.list_multi_route_decisions()
    assert len(results) == 1
    assert results[0].task == "implement auth"
    assert results[0].tools_used == ["claude-code"]


def test_list_multi_route_decisions_limit(ledger):
    for i in range(5):
        st = SubTask(task_type="impl", prompt=f"task {i}", preferred_tool="claude-code")
        d = MultiRouteDecision(
            task=f"task {i}",
            subtasks=[st],
            tools_used=["claude-code"],
            result_id=f"r{i}",
        )
        ledger.insert_multi_route_decision(d)
    results = ledger.list_multi_route_decisions(limit=3)
    assert len(results) == 3


def test_insert_idempotent(ledger):
    d = _make_decision()
    ledger.insert_multi_route_decision(d)
    ledger.insert_multi_route_decision(d)
    results = ledger.list_multi_route_decisions()
    assert len(results) == 1
