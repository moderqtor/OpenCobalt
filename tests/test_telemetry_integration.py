"""Telemetry integration tests for ArtifactBus and ConvergenceChecker."""
import time
import uuid
from unittest.mock import MagicMock

from opencobalt.core.artifact_bus import AgentArtifact, ArtifactBus, ArtifactType
from opencobalt.core.convergence_checker import ConvergenceChecker
from opencobalt.core.telemetry import TelemetryStore


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
    bus.publish(artifact)  # no telemetry_session — must not raise


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
    result = checker.check(["tests"])  # no telemetry_session — must not raise
    assert result.passed
