"""Artifact hashing and verification for Receipt-Backed Execution v0.

SHA-256 over streamed file bytes. Hashing proves integrity (the file has not
changed since attach), not safety or correctness of its contents.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .models import ARTIFACT_TYPES, ExecutionArtifact

_CHUNK_BYTES = 1024 * 1024


def hash_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file, reading in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def attach_artifact(
    path: str | Path,
    *,
    source_runtime: str,
    artifact_type: str = "unknown",
    session_id: str | None = None,
    plan_id: str | None = None,
    execution_id: str | None = None,
    summary: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ExecutionArtifact:
    """Hash a local file and return an artifact record. Raises FileNotFoundError."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"artifact file not found: {resolved}")
    normalized_type = artifact_type if artifact_type in ARTIFACT_TYPES else "unknown"
    return ExecutionArtifact(
        session_id=session_id,
        plan_id=plan_id,
        execution_id=execution_id,
        source_runtime=source_runtime,
        artifact_type=normalized_type,
        path=str(resolved),
        sha256=hash_file(resolved),
        size_bytes=resolved.stat().st_size,
        summary=summary,
        metadata=metadata or {},
    )


class ArtifactVerification(BaseModel):
    artifact_id: str
    path: str
    verified: bool
    reason: str
    expected_sha256: str
    actual_sha256: str | None = None


def verify_artifact(artifact: ExecutionArtifact) -> ArtifactVerification:
    """Recompute the hash of an attached artifact and compare."""
    path = Path(artifact.path)
    if not path.is_file():
        return ArtifactVerification(
            artifact_id=artifact.artifact_id,
            path=artifact.path,
            verified=False,
            reason="file missing",
            expected_sha256=artifact.sha256,
        )
    actual = hash_file(path)
    if actual == artifact.sha256:
        return ArtifactVerification(
            artifact_id=artifact.artifact_id,
            path=artifact.path,
            verified=True,
            reason="sha256 match",
            expected_sha256=artifact.sha256,
            actual_sha256=actual,
        )
    return ArtifactVerification(
        artifact_id=artifact.artifact_id,
        path=artifact.path,
        verified=False,
        reason="sha256 mismatch (file changed after attach)",
        expected_sha256=artifact.sha256,
        actual_sha256=actual,
    )
