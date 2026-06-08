"""Telemetry integration tests for ArtifactBus, ConvergenceChecker, and optional-session components."""
import json
import time
import uuid
from unittest.mock import MagicMock, patch

from opencobalt.core.artifact_bus import AgentArtifact, ArtifactBus, ArtifactType
from opencobalt.core.autonomy_engine import AutonomyEngine
from opencobalt.core.capability_index import CapabilityIndex
from opencobalt.core.convergence_checker import ConvergenceChecker
from opencobalt.core.convergence_orchestrator import ConvergenceOrchestrator
from opencobalt.core.ledger import Ledger
from opencobalt.core.mission import MissionPlanner
from opencobalt.core.telemetry import TelemetryStore
from opencobalt.core.usage_optimizer import UsageOptimizer
from opencobalt.integrations.registry import REGISTRY as INTEGRATION_REGISTRY


def test_artifact_bus_records_artifact_event(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="converge", seed_prompt="x", agent_id="claude-code")
    bus = ArtifactBus(tmp_path / "artifacts.db")
    artifact = AgentArtifact(
        id=str(uuid.uuid4()), session_id="sess-1", iteration=0, wave=0,
        producer="claude-code", type=ArtifactType.IMPL_CODE,
        content="print('hi')", metadata={}, timestamp=time.time(),
    )
    bus.publish(artifact, telemetry_session=session)
    events = store.list_events(session.run_id)
    assert any(e["event_type"] == "artifact" for e in events)


def test_artifact_bus_no_session_still_works(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    artifact = AgentArtifact(
        id=str(uuid.uuid4()), session_id="sess-1", iteration=0, wave=0,
        producer="claude-code", type=ArtifactType.IMPL_CODE,
        content="print('hi')", metadata={}, timestamp=time.time(),
    )
    bus.publish(artifact)  # no telemetry_session; must not raise


def test_convergence_checker_records_gate_pass(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="converge", seed_prompt="x", agent_id="claude-code")

    tests_gate = MagicMock()
    tests_gate.check.return_value = (True, "")
    checker = ConvergenceChecker(tests_gate=tests_gate)
    checker.check(["tests"], telemetry_session=session)

    events = store.list_events(session.run_id)
    assert any(e["event_type"] == "gate_pass" for e in events)


def test_convergence_checker_records_gate_fail(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="converge", seed_prompt="x", agent_id="claude-code")

    tests_gate = MagicMock()
    tests_gate.check.return_value = (False, "tests failed")
    checker = ConvergenceChecker(tests_gate=tests_gate)
    checker.check(["tests"], telemetry_session=session)

    events = store.list_events(session.run_id)
    assert any(e["event_type"] == "gate_fail" for e in events)


def test_convergence_checker_no_session_still_works():
    tests_gate = MagicMock()
    tests_gate.check.return_value = (True, "")
    checker = ConvergenceChecker(tests_gate=tests_gate)
    result = checker.check(["tests"])  # no telemetry_session; must not raise
    assert result.passed


def test_convergence_orchestrator_accepts_session(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="converge", seed_prompt="build auth", agent_id="claude-code")
    ledger = Ledger(tmp_path / "ledger.db")

    from opencobalt.core.convergence_checker import ConvergenceResult
    checker = MagicMock()
    checker.check.return_value = ConvergenceResult(
        passed=True, tests_ok=True, verifier_ok=None,
        verifier_score=None, retry_count=0, feedback="ok",
    )
    with patch("opencobalt.core.convergence_orchestrator.subprocess") as mock_sub, \
         patch("opencobalt.core.convergence_orchestrator.AutoCommitter"):
        mock_sub.run.return_value = MagicMock(returncode=0, stdout="done", stderr="")
        orch = ConvergenceOrchestrator(ledger=ledger, checker=checker)
        orch.run("build auth module", telemetry_session=session)


def test_autonomy_engine_accepts_session(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="auto", seed_prompt="finish app", agent_id="claude-code")
    ledger = Ledger(tmp_path / "ledger.db")
    engine = AutonomyEngine(ledger=ledger)
    run = engine.start("finish app", telemetry_session=session)
    assert run["status"] == "running"


def test_mission_planner_accepts_session(tmp_path):
    from opencobalt.core.autonomy_policy import PermissionEnvelope
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="mission", seed_prompt="make money", agent_id="claude-code")
    ledger = Ledger(tmp_path / "ledger.db")
    bus = MagicMock()
    planner = MissionPlanner(ledger=ledger, artifact_bus=bus)
    result = planner.plan(
        seed_goal="make money",
        profile="balanced",
        envelope=PermissionEnvelope(allowed_actions=[], denied_actions=[]),
        telemetry_session=session,
    )
    assert "run_id" in result


def test_capability_index_accepts_session(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="discover", seed_prompt="x", agent_id="claude-code")
    index = CapabilityIndex()
    entries = index.discover(telemetry_session=session)
    assert isinstance(entries, list)


def test_capability_index_records_skill_and_connector_events(tmp_path, monkeypatch):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="discover", seed_prompt="x", agent_id="claude-code")
    monkeypatch.setattr(INTEGRATION_REGISTRY["claude-code"], "install_check", lambda: True)

    CapabilityIndex().discover(telemetry_session=session)

    payloads = [
        (event["event_type"], json.loads(event["payload_json"]))
        for event in store.list_events(session.run_id)
    ]
    assert ("skill_use", {"skill_id": "file-reader"}) in payloads
    assert any(
        event_type == "connector_use" and payload["connector_id"] == "claude-code"
        for event_type, payload in payloads
    )


def test_capability_index_no_session_still_works():
    index = CapabilityIndex()
    entries = index.discover()
    assert isinstance(entries, list)


def test_usage_optimizer_no_switch_no_event(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="optimize", seed_prompt="x", agent_id="claude-code")
    ledger = Ledger(tmp_path / "ledger.db")
    optimizer = UsageOptimizer(ledger=ledger)
    optimizer.choose_tool(
        task_type="impl",
        profile="balanced",
        router_scores={"claude-code": 10, "ollama": 5},
        telemetry_session=session,
    )
    events = store.list_events(session.run_id)
    assert not any(e["event_type"] == "agent_switch" for e in events)


def test_usage_optimizer_switch_records_event(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="optimize", seed_prompt="x", agent_id="claude-code")
    ledger = Ledger(tmp_path / "ledger.db")
    benchmark_store = MagicMock()
    benchmark_store.get_best_for_task_type.return_value = "ollama"
    optimizer = UsageOptimizer(ledger=ledger, benchmark_store=benchmark_store)
    choice = optimizer.choose_tool(
        task_type="impl",
        profile="balanced",
        router_scores={"claude-code": 5, "ollama": 5},
        telemetry_session=session,
    )
    assert choice.tool == "ollama"
    events = store.list_events(session.run_id)
    assert any(e["event_type"] == "agent_switch" for e in events)
