"""Tests for Phase 14 autonomy policy defaults and permissions."""

from __future__ import annotations

from pathlib import Path

from opencobalt.core.autonomy_policy import AutonomyPolicy, PermissionEnvelope, PolicyStore


def test_default_policy_is_local_first_and_commit_not_push() -> None:
    policy = AutonomyPolicy.default()

    assert policy.auto_test is True
    assert policy.auto_retry is True
    assert policy.auto_commit is True
    assert policy.auto_push is False
    assert policy.api_usage is False
    assert policy.push_requires_explicit is True


def test_permission_envelope_denies_external_actions_unless_allowed() -> None:
    envelope = PermissionEnvelope(
        allowed_actions=["web-research", "local-build"],
        denied_actions=["purchases", "messages"],
    )

    assert envelope.permits("local-build") is True
    assert envelope.permits("web-research") is True
    assert envelope.permits("purchases") is False
    assert envelope.permits("messages") is False
    assert envelope.permits("deploy-preview") is False


def test_policy_store_round_trips_boolean_settings(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path / "ledger.db")

    assert store.get_policy().auto_commit is True
    store.set("auto_commit", "false")
    store.set("push_requires_explicit", "true")

    policy = store.get_policy()
    assert policy.auto_commit is False
    assert policy.push_requires_explicit is True


def test_profile_max_keeps_api_usage_disabled_by_default() -> None:
    policy = AutonomyPolicy.for_profile("max")

    assert policy.profile == "max"
    assert policy.use_limits == "max"
    assert policy.api_usage is False
    assert policy.auto_push is False
