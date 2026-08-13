from __future__ import annotations

import pytest

from opencobalt.personal_ai.models import AISettings, PersonaVersion
from opencobalt.personal_ai.router import (
    NoEligibleRouteError,
    PersonalAIRouter,
    ProviderSnapshot,
    RoutingRequest,
    classify_capability_role,
    classify_requirements,
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
    readiness_state: str = "unknown",
    authentication_state: str = "unknown",
    model_id: str | None = None,
    capability_roles: frozenset[str] = frozenset(),
) -> ProviderSnapshot:
    return ProviderSnapshot(
        provider_id=provider_id,
        model_id=model_id or f"{provider_id}-model",
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
        readiness_state=readiness_state,
        authentication_state=authentication_state,
        capability_roles=capability_roles,
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
    assert plan.record.approval_requirements == [
        "explicit human approval required before any consequential action based on this answer"
    ]
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
        capabilities=frozenset({"chat", "coding"}),
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


def test_persona_affinity_accepts_normalized_runtime_identity():
    router = PersonalAIRouter()
    persona = PersonaVersion(
        persona_version_id="pver-builder-v1",
        persona_id="builder",
        version=1,
        provider_affinities={"codex-cli": 10},
    )
    codex = ProviderSnapshot(
        provider_id="codex",
        model_id=None,
        runtime_id="codex-cli",
        provider_family="openai",
        available=True,
        local=False,
        requires_network=True,
        capabilities=frozenset({"chat", "coding"}),
    )

    plan = router.route(_request("Explain the implementation"), [codex], persona_version=persona)

    assert plan.candidates[0].score_components["persona_affinity"] == 10


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
    assert plan.record.approval_requirements == [
        "human review required before any external or mutating action based on this answer"
    ]
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


def test_unknown_cloud_auth_is_ranked_below_no_auth_local_runtime_without_overrides():
    router = PersonalAIRouter()
    cloud = _provider(
        "codex",
        local=False,
        requires_network=True,
        provider_family="openai",
        authentication_state="unknown",
        readiness_state="unknown",
    )
    local = _provider(
        "ollama",
        local=True,
        requires_network=False,
        cost_category="free",
        authentication_state="not_required",
        readiness_state="unknown",
    )

    plan = router.route(_request("Explain this concept"), [cloud, local])

    assert plan.record.selected_provider == "ollama"
    cloud_candidate = next(item for item in plan.candidates if item.provider_id == "codex")
    local_candidate = next(item for item in plan.candidates if item.provider_id == "ollama")
    assert cloud_candidate.score_components["readiness_evidence"] == -3
    assert local_candidate.score_components["readiness_evidence"] == 2
    assert any("authentication unknown" in reason for reason in cloud_candidate.reasons)
    assert any("authentication not required" in reason for reason in local_candidate.reasons)


KETAMINE_PROMPT = (
    "Explain in 3-4 paragraphs why ketamine's NMDA receptor antagonism can produce "
    "dissociation. Include the major circuit-level hypothesis, but distinguish "
    "established pharmacology from more speculative network-level explanations."
)


def _cheap_local(**changes: object) -> ProviderSnapshot:
    values = dict(
        provider_id="ollama",
        local=True,
        requires_network=False,
        cost_category="free",
        quality_tier="weak",
        latency_category="low",
        capabilities=frozenset({"chat", "coding", "research", "file_analysis"}),
        authentication_state="not_required",
    )
    values.update(changes)
    return _provider(**values)


def _strong_cloud(**changes: object) -> ProviderSnapshot:
    values = dict(
        provider_id="antigravity",
        local=False,
        requires_network=True,
        cost_category="standard",
        quality_tier="strong",
        latency_category="high",
        capabilities=frozenset({"chat", "coding", "research", "file_analysis"}),
        authentication_state="unknown",
    )
    values.update(changes)
    return _provider(**values)


def test_substring_log_does_not_classify_scientific_prose_as_file_analysis():
    assert classify_task(KETAMINE_PROMPT) != "file_analysis"
    assert classify_task(KETAMINE_PROMPT) == "general_reasoning"
    assert classify_task("Analyze this PDF file") == "file_analysis"
    assert classify_task("Review the error log") == "file_analysis"
    assert classify_task("Offer a difficult explanation of receptor antagonism") == "general_reasoning"


def test_scientific_prompt_has_high_reasoning_and_factual_requirements():
    requirements = classify_requirements(
        KETAMINE_PROMPT, "general_reasoning", "moderate", "fast_answer"
    )
    assert requirements.domain == "scientific"
    assert requirements.reasoning_quality == "high"
    assert requirements.factual_sensitivity == "high"


def test_arithmetic_prefers_cheap_local_over_strong_cloud():
    plan = PersonalAIRouter().route(_request("17 * 23"), [_strong_cloud(), _cheap_local()])
    assert plan.task_complexity == "simple"
    assert plan.requirements.reasoning_quality == "low"
    assert plan.record.selected_provider == "ollama"


def test_simple_extraction_prefers_cheap_local_over_strong_cloud():
    plan = PersonalAIRouter().route(
        _request("Extract the names from this list: Alice, Bob, Cara"),
        [_strong_cloud(), _cheap_local()],
    )
    assert plan.record.selected_provider == "ollama"
    assert plan.requirements.reasoning_quality == "low"


def test_nuanced_scientific_reasoning_prefers_stronger_eligible_model():
    local = _cheap_local()
    strong = _strong_cloud(model_id="gemini-3.1-pro-high")
    standard = _strong_cloud(
        provider_id="antigravity-flash",
        quality_tier="standard",
        cost_category="low",
        latency_category="low",
        model_id="gemini-3.6-flash-low",
    )
    plan = PersonalAIRouter().route(_request(KETAMINE_PROMPT), [local, standard, strong])
    assert plan.task_class == "general_reasoning"
    assert plan.record.selected_provider == "antigravity"
    assert plan.record.selected_model == "gemini-3.1-pro-high"
    local_candidate = next(item for item in plan.candidates if item.provider_id == "ollama")
    strong_candidate = next(item for item in plan.candidates if item.model_id == "gemini-3.1-pro-high")
    assert strong_candidate.score > local_candidate.score
    assert strong_candidate.score_components["reasoning_quality_fit"] == 12
    assert local_candidate.score_components["factual_sensitivity_fit"] == -15
    assert any("scientific reasoning quality requirement: +12" in reason for reason in strong_candidate.reasons)
    assert any(
        "weak model quality penalty for evidence-sensitive synthesis: -15" in reason
        for reason in local_candidate.reasons
    )
    assert all(reason.strip() for reason in local_candidate.reasons)


def test_local_only_still_selects_local_or_fails_closed():
    router = PersonalAIRouter()
    local = _cheap_local()
    cloud = _strong_cloud()
    forced_local = router.route(_request(KETAMINE_PROMPT, local_only=True), [cloud, local])
    assert forced_local.record.selected_provider == "ollama"
    cloud_candidate = next(item for item in forced_local.candidates if item.provider_id == "antigravity")
    assert cloud_candidate.eligible is False
    assert cloud_candidate.rejection_reason == "strict local-only policy excludes network/cloud provider"
    with pytest.raises(NoEligibleRouteError):
        router.route(_request(KETAMINE_PROMPT, local_only=True), [cloud])


def _cursor_coding(**changes: object) -> ProviderSnapshot:
    values = dict(
        provider_id="cursor",
        local=False,
        requires_network=True,
        cost_category="standard",
        quality_tier="strong",
        latency_category="standard",
        capabilities=frozenset({"coding", "file_analysis", "planning", "repository"}),
        capability_roles=frozenset({"coding_analysis", "coding_agent"}),
        authentication_state="verified",
        readiness_state="ready",
    )
    values.update(changes)
    return _provider(**values)


def test_arithmetic_does_not_select_a_coding_agent_runtime():
    plan = PersonalAIRouter().route(
        _request("17 * 23"),
        [_cursor_coding(), _cheap_local(), _strong_cloud()],
    )
    assert plan.capability_role == "cheap_local"
    assert plan.record.selected_provider == "ollama"
    cursor = next(item for item in plan.candidates if item.provider_id == "cursor")
    assert cursor.eligible is False
    assert "coding-agent runtime is not eligible" in (cursor.rejection_reason or "")


def test_scientific_reasoning_does_not_select_a_coding_agent_runtime():
    plan = PersonalAIRouter().route(
        _request(KETAMINE_PROMPT),
        [_cursor_coding(), _cheap_local(), _strong_cloud()],
    )
    assert plan.capability_role == "strong_reasoning"
    assert plan.record.selected_provider == "antigravity"
    cursor = next(item for item in plan.candidates if item.provider_id == "cursor")
    assert cursor.eligible is False


def test_research_role_does_not_select_a_coding_agent_runtime():
    plan = PersonalAIRouter().route(
        _request("Research Medicare periodontal coverage"),
        [_cursor_coding(), _strong_cloud(capabilities=frozenset({"chat", "research"}))],
    )
    assert plan.capability_role == "research"
    assert plan.record.selected_provider == "antigravity"
    cursor = next(item for item in plan.candidates if item.provider_id == "cursor")
    assert cursor.eligible is False


def test_repository_code_explanation_makes_coding_analysis_eligible():
    repo = "/workspace/OpenCobalt"
    plan = PersonalAIRouter().route(
        _request(
            "Explain what src/opencobalt/personal_ai/router.py does",
            project_path=repo,
        ),
        [_cursor_coding(), _cheap_local(), _strong_cloud()],
    )
    assert plan.capability_role == "coding_analysis"
    cursor = next(item for item in plan.candidates if item.provider_id == "cursor")
    assert cursor.eligible is True
    assert cursor.score_components["role_fit"] == 24
    assert plan.record.metadata["capability_role"] == "coding_analysis"


def test_repository_refactor_prefers_coding_agent_runtime():
    repo = "/workspace/OpenCobalt"
    plan = PersonalAIRouter().route(
        _request(
            "Refactor router.py to separate candidate generation from candidate scoring and run tests",
            project_path=repo,
        ),
        [_cursor_coding(), _cheap_local(), _strong_cloud()],
    )
    assert plan.capability_role == "coding_agent"
    assert plan.record.selected_provider == "cursor"
    local = next(item for item in plan.candidates if item.provider_id == "ollama")
    cloud = next(item for item in plan.candidates if item.provider_id == "antigravity")
    assert local.eligible is False
    assert cloud.eligible is False
    assert "coding_agent" in (local.rejection_reason or "")


def test_general_chat_does_not_route_to_coding_agent_even_with_a_repo_attached():
    plan = PersonalAIRouter().route(
        _request("What is the capital of France?", project_path="/workspace/OpenCobalt"),
        [_cursor_coding(), _cheap_local(), _strong_cloud()],
    )
    assert plan.capability_role in {"cheap_local", "fast_general"}
    assert plan.record.selected_provider != "cursor"
    cursor = next(item for item in plan.candidates if item.provider_id == "cursor")
    assert cursor.eligible is False


def test_local_only_excludes_cursor_coding_runtime():
    repo = "/workspace/OpenCobalt"
    plan = PersonalAIRouter().route(
        _request(
            "Explain what src/opencobalt/personal_ai/router.py does",
            project_path=repo,
            local_only=True,
        ),
        [_cursor_coding(), _cheap_local()],
    )
    cursor = next(item for item in plan.candidates if item.provider_id == "cursor")
    assert cursor.eligible is False
    assert cursor.rejection_reason == "strict local-only policy excludes network/cloud provider"
    assert plan.record.selected_provider == "ollama"


def test_coding_agent_without_repository_path_is_not_classified_as_agent_work():
    role = classify_capability_role(
        "Refactor router.py and run tests",
        "coding",
        "moderate",
        classify_requirements("Refactor router.py and run tests", "coding", "moderate"),
        project_path=None,
    )
    assert role != "coding_agent"


def test_evidence_questions_classify_as_research():
    assert classify_task("What evidence supports and weakens a screening checkpoint?") == "research"


def test_reflective_prompts_classify_as_personal_reflection():
    assert classify_task("I miss someone, and I am unsure why.") == "personal_reflection"
