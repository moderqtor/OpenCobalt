import pytest
from opencobalt.core.benchmark import BenchmarkRecord, BenchmarkStore


@pytest.fixture
def store(tmp_path):
    return BenchmarkStore(db_path=tmp_path / "bench.db")


def test_record_with_subagent_id(store):
    r = BenchmarkRecord(
        agent_id="impl-agent",
        task_id="t1",
        task_type="impl",
        latency_ms=200,
        success=True,
        model_used="claude-code",
        tier="executive",
        score=0.85,
        subagent_id="impl-agent",
        prompt_style="imperative",
    )
    store.record(r)
    rows = store.list_recent(limit=1)
    assert rows[0]["subagent_id"] == "impl-agent"
    assert rows[0]["prompt_style"] == "imperative"


def test_record_without_subagent_fields_defaults_none(store):
    r = BenchmarkRecord(
        agent_id="codex-cli",
        task_id="t2",
        task_type="tests",
        latency_ms=500,
        success=True,
        model_used="codex-cli",
        tier="manager",
        score=0.7,
    )
    store.record(r)
    rows = store.list_recent(limit=1)
    assert rows[0]["subagent_id"] is None
    assert rows[0]["prompt_style"] is None


def test_leaderboard_still_works(store):
    for i in range(3):
        r = BenchmarkRecord(
            agent_id="impl-agent",
            task_id=f"t{i}",
            task_type="impl",
            latency_ms=300,
            success=True,
            model_used="claude-code",
            tier="executive",
            score=0.9,
        )
        store.record(r)
    lb = store.get_leaderboard()
    assert lb[0]["agent_id"] == "impl-agent"
