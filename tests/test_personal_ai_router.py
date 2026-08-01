from __future__ import annotations

import pytest

from opencobalt.personal_ai.models import AISettings, PersonaVersion
from opencobalt.personal_ai.router import (
    NoEligibleRouteError,
    PersonalAIRouter,
    ProviderSnapshot,
    RoutingRequest,
    classify_task,
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
    latency_category: str = "standard",
    historical_success_signal: int = 0,
    quota_pressure: int = 0,
    provider_priority: int = 0,
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
        latency_category=latency_category,
        historical_success_signal=historical_success_signal,
        quota_pressure=quota_pressure,
        provider_priority=provider_priority,
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
        cost_category="standard",
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


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("Explain this concept", "general_reasoning"),
        ("Reflect on how I feel", "personal_reflection"),
        ("Research the source material", "research"),
        ("Implement a parser", "coding"),
        ("Update this repository", "repository_execution"),
        ("Write a short brief", "writing"),
        ("Edit this paragraph", "editing"),
        ("Analyze this PDF file", "file_analysis"),
        ("Plan next week", "planning"),
        ("Brainstorm product ideas", "creative_ideation"),
        ("Analyze this CSV dataset", "data_analysis"),
        ("Run the requested tool", "tool_operation"),
        ("Create a multi-step mission", "multi_step_mission"),
    ],
)
def test_task_classification_uses_the_explicit_router_vocabulary(prompt, expected):
    assert classify_task(prompt) == expected


def test_privacy_policy_and_explicit_reasoning_inputs_are_visible_in_route_metadata():
    router = PersonalAIRouter()
    provider = _provider("local", local=True, requires_network=False)

    plan = router.route(
        _request(
            "Explain this concept",
            privacy_mode="standard",
            cognitive_policy="deep_analysis",
            reasoning_effort="high",
            settings=AISettings(privacy_policy="sensitive"),
        ),
        [provider],
    )

    assert plan.privacy_classification == "sensitive"
    assert plan.task_complexity == "complex"
    assert plan.record.metadata["privacy_mode"] == "standard"
    assert plan.record.metadata["cognitive_policy"] == "deep_analysis"
    assert plan.record.metadata["reasoning_effort"] == "high"
    assert set(plan.candidates[0].score_components) >= {
        "latency_fit",
        "historical_success",
        "quota_pressure",
        "provider_priority",
    }


def test_cost_ceiling_is_an_eligibility_rule_with_a_visible_rejection_reason():
    router = PersonalAIRouter()
    affordable = _provider("affordable", local=True, requires_network=False, cost_category="low")
    expensive = _provider("expensive", local=True, requires_network=False, cost_category="high")

    plan = router.route(
        _request("Explain this concept", settings=AISettings(cost_ceiling_category="low")),
        [expensive, affordable],
    )

    assert plan.record.selected_provider == "affordable"
    expensive_candidate = next(
        candidate for candidate in plan.candidates if candidate.provider_id == "expensive"
    )
    assert expensive_candidate.eligible is False
    assert expensive_candidate.rejection_reason == (
        "provider cost category 'high' exceeds configured ceiling 'low'"
    )


def test_complex_implementation_rejects_a_weak_model_even_when_it_is_free():
    router = PersonalAIRouter()
    weak = _provider(
        "weak-free",
        local=True,
        requires_network=False,
        cost_category="free",
        quality_tier="weak",
        capabilities=frozenset({"chat", "coding"}),
    )
    strong = _provider(
        "strong",
        local=True,
        requires_network=False,
        quality_tier="strong",
        capabilities=frozenset({"chat", "coding"}),
    )

    plan = router.route(
        _request("Implement a comprehensive parser across multiple modules"),
        [weak, strong],
    )

    assert plan.task_complexity == "complex"
    assert plan.record.selected_provider == "strong"
    weak_candidate = next(candidate for candidate in plan.candidates if candidate.provider_id == "weak-free")
    assert weak_candidate.eligible is False
    assert weak_candidate.rejection_reason == "complex implementation requires a strong model"


def test_bounded_latency_history_quota_and_priority_signals_are_scored_explicitly():
    router = PersonalAIRouter()
    stronger_evidence = _provider(
        "evidence",
        local=True,
        requires_network=False,
        latency_category="low",
        historical_success_signal=6,
        quota_pressure=2,
        provider_priority=4,
    )
    weaker_evidence = _provider(
        "pressured",
        local=True,
        requires_network=False,
        latency_category="high",
        historical_success_signal=-3,
        quota_pressure=8,
        provider_priority=-2,
    )

    plan = router.route(_request("Explain this concept"), [weaker_evidence, stronger_evidence])

    assert plan.record.selected_provider == "evidence"
    components = plan.candidates[0].score_components
    assert components["latency_fit"] == 8
    assert components["historical_success"] == 6
    assert components["quota_pressure"] == -2
    assert components["provider_priority"] == 4
