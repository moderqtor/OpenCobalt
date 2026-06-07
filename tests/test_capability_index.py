"""Tests for local capability discovery."""

from __future__ import annotations

from opencobalt.core.capability_index import CapabilityIndex


def test_capability_index_lists_skills_integrations_and_subagents() -> None:
    capabilities = CapabilityIndex().discover()
    ids = {cap.id for cap in capabilities}

    assert "skill:file-reader" in ids
    assert "integration:claude-code" in ids
    assert "subagent:test-gen" in ids


def test_capability_index_marks_cli_availability(monkeypatch) -> None:
    monkeypatch.setattr(
        "shutil.which",
        lambda binary: f"/usr/bin/{binary}" if binary == "codex" else None,
    )

    capabilities = CapabilityIndex().discover()
    codex = next(cap for cap in capabilities if cap.id == "cli:codex-cli")
    claude = next(cap for cap in capabilities if cap.id == "cli:claude-code")

    assert codex.available is True
    assert claude.available is False
