from __future__ import annotations

import pytest

from opencobalt.personal_ai.models import AISettings, PersonaVersion
from opencobalt.personal_ai.router import (
    NoEligibleRouteError,
    PersonalAIRouter,
    ProviderSnapshot,
    RoutingRequest,
)


def _provider(
    provider_id: str,
    *,
    local: bool,
    requires_network: bool,
    cost_category: str = "standard",
    quality_tier: str = "strong",
    capabilities: frozenset[str] = frozenset({"chat"}),
    tools: frozenset[str] = frozenset(),
    skills: frozenset[str] = frozenset(),
    provider_family: str | None = None,
    available: bool = True,
) -> ProviderSnapshot:
    return ProviderSnapshot(
        provider_id=provider_id,
        model_id=f"{provider_id}-model",
        runtime_id=f"{provider_id}-runtime",
        provider_family=provider_family or provider_id,
        available=available,
        local=local,
        requires_network=requires_network,
        cost_category=cost_category,
        quality_tier=quality_tier,
        capabilities=capabilities,
        tool_names=tools,
        skill_names=skills,
    )


def _request(prompt: str, **changes: object) -> RoutingRequest:
    values: dict[str, object] = {
        "request_id": "req-router",
        "conversation_id": "conv-router",
        "request_message_id": "msg-router",
        "prompt": prompt,
        "requested_persona_id": "analytical",
    }
    values.update(changes)
    return RoutingRequest(**values)


def test_security_work_is_sensitive_red_and_rejects_a_weak_free_local_model():
    router = PersonalAIRouter()
    local = _provider(
        "ollama",
        local=True,
        requires_network=False,
        cost_category="free",
        quality_tier="weak",
        capabilities=frozenset({"chat", "security", "repository"}),
    )
    strong = _provider(
        "codex-cli",
        local=False,
        requires_network=True,
        capabilities=frozenset({"chat", "security", "repository"}),
    )

    plan = router.route(_request("Audit this repository for leaked API keys"), [local, strong])

    assert plan.task_class == "security_review"
    assert plan.privacy_classification == "sensitive"
    assert plan.risk_classification == "red"
    assert plan.record.selected_provider == "codex-cli"
    weak_candidate = next(candidate for candidate in plan.candidates if candidate.provider_id == "ollama")
    assert weak_candidate.eligible is False
    assert "strong model" in weak_candidate.rejection_reason
    assert set(weak_candidate.score_components) >= {
        "availability",
        "capability_fit",
        "cost_fit",
        "persona_affinity",
        "privacy_fit",
        "risk_fit",
        "tool_fit",
    }


def test_strict_local_only_excludes_network_and_cloud_candidates():
    router = PersonalAIRouter()
    local = _provider(
        "ollama",
        local=True,
        requires_network=False,
        capabilities=frozenset({"chat", "coding"}),
    )
    cloud = _provider(
        "codex-cli",
        local=False,
        requires_network=True,
        capabilities=frozenset({"chat", "coding"}),
    )

    plan = router.route(
        _request("Implement a parser", local_only=True),
        [cloud, local],
    )

    assert plan.record.selected_provider == "ollama"
    cloud_candidate = next(candidate for candidate in plan.candidates if candidate.provider_id == "codex-cli")
    assert cloud_candidate.eligible is False
    assert cloud_candidate.rejection_reason == "strict local-only policy excludes network/cloud provider"


def test_manual_provider_and_model_override_is_honored_when_available():
    router = PersonalAIRouter()
    preferred = _provider("preferred", local=False, requires_network=True)
    override = ProviderSnapshot(
        provider_id="override",
        model_id="selected-model",
        runtime_id="override-runtime",
        provider_family="override",
        available=True,
        local=False,
        requires_network=True,
        cost_category="high",
        quality_tier="strong",
        capabilities=frozenset({"chat"}),
    )

    plan = router.route(
        _request("Explain the tradeoff", provider_override="override", model_override="selected-model"),
        [preferred, override],
    )

    assert plan.record.selected_provider == "override"
    assert plan.record.selected_model == "selected-model"
    assert "manual provider override honored" in plan.record.reasons
    assert "manual model override honored" in plan.record.reasons


def test_persona_affinity_is_a_prior_and_native_persona_mismatch_is_disclosed():
    router = PersonalAIRouter()
    native_persona = PersonaVersion(
        persona_version_id="pver-claude-native-v1",
        persona_id="claude-native",
        version=1,
        provider_affinities={"claude": 10},
        native_provider_family="anthropic",
    )
    claude = _provider("claude", local=False, requires_network=True, provider_family="anthropic")
    local = _provider("local", local=True, requires_network=False, provider_family="local")

    affinity_plan = router.route(
        _request("Think through this decision", requested_persona_id="claude-native"),
        [local, claude],
        persona_version=native_persona,
    )
    assert affinity_plan.record.selected_provider == "claude"
    assert affinity_plan.record.actual_persona_id == "claude-native"
    assert affinity_plan.record.persona_provider_mismatch is None

    mismatch_plan = router.route(
        _request("Think through this decision", requested_persona_id="claude-native", local_only=True),
        [local],
        persona_version=native_persona,
    )
    assert mismatch_plan.record.actual_persona_id == "provider-native"
    assert mismatch_plan.record.persona_provider_mismatch is not None
    assert "anthropic" in mismatch_plan.record.persona_provider_mismatch
    assert "local" in mismatch_plan.record.persona_provider_mismatch


def test_unavailable_and_tool_incompatible_candidates_have_meaningful_rejections():
    router = PersonalAIRouter()
    unavailable = _provider("offline", local=True, requires_network=False, available=False)
    no_tools = _provider(
        "no-tools",
        local=True,
        requires_network=False,
        capabilities=frozenset({"chat", "repository"}),
    )

    with pytest.raises(NoEligibleRouteError, match="no eligible provider") as error:
        router.route(
            _request("Inspect the repository", requested_tools=("repository-read",)),
            [unavailable, no_tools],
        )

    candidates = error.value.candidates
    assert {candidate.provider_id for candidate in candidates} == {"offline", "no-tools"}
    assert next(candidate for candidate in candidates if candidate.provider_id == "offline").rejection_reason == (
        "provider is unavailable"
    )
    assert "does not support required tools" in next(
        candidate for candidate in candidates if candidate.provider_id == "no-tools"
    ).rejection_reason


def test_route_output_is_persistence_compatible_and_never_reports_a_fallback_execution():
    router = PersonalAIRouter()
    provider = _provider(
        "builder",
        local=True,
        requires_network=False,
        capabilities=frozenset({"chat", "coding", "repository"}),
        tools=frozenset({"repository-read"}),
        skills=frozenset({"pytest"}),
    )

    plan = router.route(
        _request(
            "Review this repository and run focused tests",
            requested_tools=("repository-read",),
            requested_skills=("pytest",),
            settings=AISettings(skill_permissions="allow_builtin"),
        ),
        [provider],
    )

    assert plan.record.outcome_status == "planned"
    assert plan.record.fallback_events == []
    assert plan.record.selected_tools == ["repository-read"]
    assert plan.record.selected_skills == ["pytest"]
    assert plan.record.verification_strategy == "repository_review"
    assert plan.candidates[0].route_id == plan.record.route_id
