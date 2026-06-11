import hashlib
import time
import uuid
from pathlib import Path

from opencobalt.core.artifact_bus import (
    AgentArtifact,
    ArtifactBus,
    ArtifactType,
    WorkArtifact,
    build_work_artifact,
)


def _artifact(
    session_id: str = "sess-1",
    artifact_type: str = ArtifactType.IMPL_CODE,
    producer: str = "claude",
    content: str = "some code",
    wave: int = 0,
    timestamp: float | None = None,
) -> AgentArtifact:
    return AgentArtifact(
        id=str(uuid.uuid4()),
        session_id=session_id,
        iteration=0,
        wave=wave,
        producer=producer,
        type=artifact_type,
        content=content,
        metadata={},
        timestamp=timestamp if timestamp is not None else time.time(),
    )


def test_publish_and_subscribe(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    a = _artifact()
    bus.publish(a)
    results = bus.subscribe([ArtifactType.IMPL_CODE], "sess-1")
    assert len(results) == 1
    assert results[0].content == "some code"
    assert results[0].producer == "claude"


def test_subscribe_filters_by_type(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    bus.publish(_artifact(artifact_type=ArtifactType.IMPL_CODE, content="impl"))
    bus.publish(_artifact(artifact_type=ArtifactType.TEST_CODE, content="tests"))
    impl_results = bus.subscribe([ArtifactType.IMPL_CODE], "sess-1")
    assert len(impl_results) == 1
    assert impl_results[0].type == ArtifactType.IMPL_CODE


def test_subscribe_filters_by_session(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    bus.publish(_artifact(session_id="sess-1"))
    bus.publish(_artifact(session_id="sess-2"))
    results = bus.subscribe([ArtifactType.IMPL_CODE], "sess-1")
    assert len(results) == 1


def test_subscribe_multiple_types(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    bus.publish(_artifact(artifact_type=ArtifactType.IMPL_CODE))
    bus.publish(_artifact(artifact_type=ArtifactType.TEST_CODE))
    results = bus.subscribe([ArtifactType.IMPL_CODE, ArtifactType.TEST_CODE], "sess-1")
    assert len(results) == 2


def test_latest_returns_most_recent(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    bus.publish(_artifact(content="first", timestamp=1.0))
    bus.publish(_artifact(content="second", timestamp=2.0))
    result = bus.latest(ArtifactType.IMPL_CODE, "sess-1")
    assert result is not None
    assert result.content == "second"


def test_latest_returns_none_for_missing(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    assert bus.latest(ArtifactType.IMPL_CODE, "no-session") is None


def test_context_for_builds_string(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    a = _artifact(artifact_type=ArtifactType.IMPL_CODE, producer="claude", content="the impl")
    bus.publish(a)
    ctx = bus.context_for([ArtifactType.IMPL_CODE], "sess-1")
    assert "impl_code" in ctx
    assert "claude" in ctx
    assert "the impl" in ctx


def test_context_for_empty_session_returns_empty(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    ctx = bus.context_for([ArtifactType.IMPL_CODE], "no-session")
    assert ctx == ""


def test_context_for_empty_types_returns_empty(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    bus.publish(_artifact())
    ctx = bus.context_for([], "sess-1")
    assert ctx == ""


def test_error_context_auto_inject(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    err_artifact = AgentArtifact(
        id=str(uuid.uuid4()),
        session_id="sess-1",
        iteration=1,
        wave=0,
        producer="convergence-checker",
        type=ArtifactType.ERROR_CONTEXT,
        content="test failed: assertion error on line 42",
        metadata={},
        timestamp=2.0,
    )
    bus.publish(err_artifact)
    ctx = bus.context_for([ArtifactType.ERROR_CONTEXT], "sess-1")
    assert "assertion error" in ctx
    assert "convergence-checker" in ctx


def test_artifact_bus_creates_db_file(tmp_path):
    db = tmp_path / "sub" / "artifacts.db"
    ArtifactBus(db)
    assert db.exists()


def test_publish_replaces_on_same_id(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    a = _artifact()
    bus.publish(a)
    a.content = "updated"
    bus.publish(a)
    results = bus.subscribe([ArtifactType.IMPL_CODE], "sess-1")
    assert len(results) == 1
    assert results[0].content == "updated"


def test_work_artifact_has_required_fields(tmp_path):
    artifact_path = tmp_path / "report.txt"
    artifact_path.write_text("verification output", encoding="utf-8")
    artifact = build_work_artifact(
        artifact_path,
        session_id="sess-1",
        source_runtime="google-antigravity",
        artifact_type="test_output",
        summary="pytest output",
    )
    assert isinstance(artifact, WorkArtifact)
    assert artifact.session_id == "sess-1"
    assert artifact.source_runtime == "google-antigravity"
    assert artifact.artifact_type == "test_output"
    assert artifact.path == str(artifact_path)
    assert artifact.sha256 == hashlib.sha256(b"verification output").hexdigest()
    assert artifact.summary == "pytest output"


def test_work_artifact_rejects_unknown_type_with_unknown_fallback(tmp_path):
    artifact_path = tmp_path / "custom.bin"
    artifact_path.write_bytes(b"data")
    artifact = build_work_artifact(
        Path(artifact_path),
        session_id="sess-1",
        source_runtime="google-antigravity",
        artifact_type="private-antigravity-format",
    )
    assert artifact.artifact_type == "unknown"
