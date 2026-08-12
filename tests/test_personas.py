from __future__ import annotations

import sqlite3

import pytest

from opencobalt.personal_ai.personas import (
    BUILTIN_PERSONA_IDS,
    duplicate_persona,
    ensure_builtin_personas,
    render_persona_policy,
)
from opencobalt.personal_ai.store import PersonalAIStore


def test_builtin_personas_are_versioned_structured_and_idempotent(tmp_path):
    store = PersonalAIStore(tmp_path / "ledger.db")

    ensure_builtin_personas(store)
    ensure_builtin_personas(store)

    personas = store.list_personas()
    assert {persona.persona_id for persona in personas} == set(BUILTIN_PERSONA_IDS)
    analytical = store.get_persona("analytical")
    version = store.get_active_persona_version("analytical")
    assert analytical is not None
    assert analytical.name == "Analytical"
    assert analytical.built_in is True
    assert version is not None
    assert version.version == 1
    assert version.controls.directness == "very_high"
    assert version.controls.uncertainty_explicitness == "very_high"
    assert version.provider_affinities["codex-cli"] > 0
    assert "implementation" in version.allowed_cognitive_policies


def test_persona_versions_are_immutable_at_the_database_boundary(tmp_path):
    store = PersonalAIStore(tmp_path / "ledger.db")
    ensure_builtin_personas(store)
    version = store.get_active_persona_version("analytical")
    assert version is not None

    with sqlite3.connect(store.db_path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE persona_versions SET custom_instructions = ? WHERE persona_version_id = ?",
            ("changed after the fact", version.persona_version_id),
        )


def test_duplicate_persona_copies_controls_into_an_editable_custom_identity(tmp_path):
    store = PersonalAIStore(tmp_path / "ledger.db")
    ensure_builtin_personas(store)

    duplicate = duplicate_persona(store, "reflective", "Reflective for Colin")
    version = store.get_active_persona_version(duplicate.persona_id)

    assert duplicate.name == "Reflective for Colin"
    assert duplicate.built_in is False
    assert duplicate.persona_id != "reflective"
    assert version is not None
    assert version.controls.emotional_attunement == "very_high"
    assert version.version == 1


def test_rendered_policy_keeps_persona_and_provider_separate(tmp_path):
    store = PersonalAIStore(tmp_path / "ledger.db")
    ensure_builtin_personas(store)
    provider_native = store.get_active_persona_version("chatgpt-native")
    analytical = store.get_active_persona_version("analytical")
    assert provider_native is not None
    assert analytical is not None

    native_policy = render_persona_policy(provider_native, "fast_answer")
    analytical_policy = render_persona_policy(analytical, "skeptical_review")

    assert "Requested native provider family: openai" in native_policy
    assert "Do not claim provider identity" in native_policy
    assert "Cognitive policy: skeptical_review" in analytical_policy
    assert "Uncertainty explicitness: very high" in analytical_policy
    assert "Provider selected:" not in analytical_policy
