import json
import sqlite3

from opencobalt.core.telemetry import TelemetryStore


def test_schema_creates_three_tables(tmp_path):
    TelemetryStore(tmp_path / "telemetry.db")
    conn = sqlite3.connect(tmp_path / "telemetry.db")
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "telemetry_runs" in tables
    assert "telemetry_events" in tables
    assert "telemetry_scores" in tables


def test_start_run_returns_session(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="route", seed_prompt="summarize logs", agent_id="claude-code")
    assert session.run_id
    run = store.get_run(session.run_id)
    assert run["status"] == "running"
    assert run["run_type"] == "route"
    assert run["seed_prompt"] == "summarize logs"


def test_add_event_persists(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="route", seed_prompt="x", agent_id="claude-code")
    store.add_event(session.run_id, "tool_use", {"tool": "pytest"})
    events = store.list_events(session.run_id)
    assert len(events) == 1
    assert events[0]["event_type"] == "tool_use"
    assert json.loads(events[0]["payload_json"])["tool"] == "pytest"


def test_finish_run_updates_status(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="route", seed_prompt="x", agent_id="claude-code")
    store.add_event(session.run_id, "retry", {"reason": "gate failed"})
    store.add_event(session.run_id, "artifact", {"type": "code", "id": "abc"})
    store.finish_run(session.run_id, "complete")
    run = store.get_run(session.run_id)
    assert run["status"] == "complete"
    assert run["retry_count"] == 1
    assert run["artifacts_produced"] == 1
    assert run["latency_ms"] is not None


def test_save_and_get_score(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="route", seed_prompt="x", agent_id="claude-code")
    store.finish_run(session.run_id, "complete")
    score = {
        "run_id": session.run_id,
        "scored_at": "2026-06-07T00:00:00Z",
        "judge": "heuristic",
        "overall": 72,
        "output_quality": 80,
        "prompt_adherence": 75,
        "novel_ideation": 50,
        "context_handling": 50,
        "token_efficiency": 70,
        "latency_score": 85,
        "tool_appropriateness": 60,
        "task_decomposition": 50,
        "agent_selection": 50,
        "convergence_quality": 95,
        "judge_reasoning": "Decent output.",
        "heuristics": {"retry_count": 0},
    }
    store.save_score(score)
    result = store.get_score(session.run_id)
    assert result["overall"] == 72
    assert result["judge"] == "heuristic"
    run = store.get_run(session.run_id)
    assert run["status"] == "scored"


def test_list_runs(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    for i in range(3):
        s = store.start_run(run_type="route", seed_prompt=f"task {i}", agent_id="claude-code")
        store.finish_run(s.run_id, "complete")
    runs = store.list_runs(limit=10)
    assert len(runs) == 3

    runs_filtered = store.list_runs(run_type="route")
    assert len(runs_filtered) == 3

    runs_none = store.list_runs(run_type="converge")
    assert len(runs_none) == 0


def test_get_leaderboard_returns_agent_stats(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="route", seed_prompt="x", agent_id="claude-code")
    store.finish_run(session.run_id, "complete")
    score = {
        "run_id": session.run_id,
        "scored_at": "2026-06-07T00:00:00Z",
        "judge": "heuristic",
        "overall": 80,
        "output_quality": 85,
        "prompt_adherence": 75,
        "novel_ideation": 50,
        "context_handling": 60,
        "token_efficiency": 70,
        "latency_score": 90,
        "tool_appropriateness": 65,
        "task_decomposition": 55,
        "agent_selection": 60,
        "convergence_quality": 95,
        "judge_reasoning": "",
        "heuristics": {},
    }
    store.save_score(score)
    board = store.get_leaderboard()
    assert len(board) == 1
    assert board[0]["agent_id"] == "claude-code"
    assert board[0]["total"] == 1
    assert board[0]["avg_overall"] == 80.0


def test_set_raw_output(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="route", seed_prompt="x", agent_id="claude-code")
    store.set_raw_output(session.run_id, "the output", token_count_out=42)
    run = store.get_run(session.run_id)
    assert run["raw_output"] == "the output"
    assert run["token_count_out"] == 42


def test_set_summary(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="route", seed_prompt="x", agent_id="claude-code")
    store.set_summary(session.run_id, "A helpful summary.")
    run = store.get_run(session.run_id)
    assert run["summary"] == "A helpful summary."


def test_session_record_tool_use(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="route", seed_prompt="x", agent_id="claude-code")
    session.record_tool_use("pytest", success=True, latency_ms=200)
    events = store.list_events(session.run_id)
    assert events[0]["event_type"] == "tool_use"
    assert json.loads(events[0]["payload_json"])["tool"] == "pytest"


def test_session_record_output_sets_raw(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="route", seed_prompt="x", agent_id="claude-code")
    session.record_output("the result", token_count=42)
    run = store.get_run(session.run_id)
    assert run["raw_output"] == "the result"
    assert run["token_count_out"] == 42


def test_session_finish_delegates(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="route", seed_prompt="x", agent_id="claude-code")
    session.finish("complete")
    run = store.get_run(session.run_id)
    assert run["status"] == "complete"
