"""Architecture-level routing invariants: task family is not cognitive policy."""

from __future__ import annotations

import pytest

from opencobalt.personal_ai.router import (
    PersonalAIRouter,
    classify_risk,
    classify_task,
)
from tests.test_personal_ai_router import _cheap_local, _request, _strong_cloud

POLICIES = (
    "fast_answer",
    "deep_analysis",
    "skeptical_review",
    "implementation",
    "research_synthesis",
)

EXPLANATIONS = (
    "Explain the difference between TCP and UDP in three sentences.",
    "Explain why DNS caching improves performance in three sentences.",
    "Explain what an HTTP status code is in two sentences.",
    "Explain the difference between a monolith and microservices briefly.",
)


@pytest.mark.parametrize("prompt", EXPLANATIONS)
@pytest.mark.parametrize("policy", POLICIES)
def test_answer_only_explanations_are_not_coding_under_any_policy(prompt, policy):
    task = classify_task(prompt, policy)
    assert task == "general_reasoning"
    plan = PersonalAIRouter().route(
        _request(prompt, cognitive_policy=policy),
        [_cheap_local(), _strong_cloud()],
    )
    assert plan.task_class == "general_reasoning"
    assert plan.record.verification_strategy != "tests_and_diff"
    assert plan.record.autonomy_level == "answer_only"
    assert plan.record.approval_requirements == []
    assert plan.requirements.mutation_authority == "none"
    assert plan.capability_role in {"cheap_local", "fast_general"}
    assert classify_risk(prompt, plan.task_class) == "green"


@pytest.mark.parametrize("policy", POLICIES)
def test_manual_override_does_not_change_task_family_or_authority(policy):
    prompt = "Explain why DNS caching improves performance in three sentences."
    automatic = PersonalAIRouter().route(
        _request(prompt, cognitive_policy=policy),
        [_cheap_local(), _strong_cloud()],
    )
    overridden = PersonalAIRouter().route(
        _request(
            prompt,
            cognitive_policy=policy,
            provider_override="antigravity",
            model_override="antigravity-model",
        ),
        [_cheap_local(), _strong_cloud()],
    )
    assert overridden.task_class == automatic.task_class == "general_reasoning"
    assert overridden.record.autonomy_level == automatic.record.autonomy_level == "answer_only"
    assert overridden.record.verification_strategy == automatic.record.verification_strategy
    assert overridden.risk_classification == automatic.risk_classification
    assert overridden.record.selected_provider == "antigravity"


def test_incompatible_override_fails_without_reclassifying_the_task():
    prompt = "Explain what an HTTP status code is in two sentences."
    with pytest.raises(Exception, match="no eligible provider route"):
        PersonalAIRouter().route(
            _request(prompt, provider_override="cursor"),
            [_cheap_local(), _strong_cloud()],
        )
    assert classify_task(prompt, "implementation") == "general_reasoning"


def test_override_does_not_weaken_local_only():
    prompt = "Explain the difference between TCP and UDP in three sentences."
    with pytest.raises(Exception, match="no eligible provider route"):
        PersonalAIRouter().route(
            _request(prompt, local_only=True, provider_override="antigravity"),
            [_cheap_local(), _strong_cloud()],
        )


def test_routing_matrix_keeps_impossible_authority_combinations_apart():
    cases = (
        ("What is 17 times 23", "general_reasoning", "cheap_local", "none"),
        (
            "Explain the difference between TCP and UDP in three sentences.",
            "general_reasoning",
            "cheap_local",
            "none",
        ),
        (
            "Walk through the tradeoffs of a consensus protocol across partitions and failure modes",
            "general_reasoning",
            "strong_reasoning",
            "none",
        ),
        (
            "What acetaminophen dosage and contraindications apply for an adult patient with fever?",
            "general_reasoning",
            "strong_reasoning",
            "none",
        ),
        (
            "Should I settle this lawsuit or go to trial?",
            "consequential_decision",
            "strong_reasoning",
            "explicit",
        ),
        (
            "What is the latest reported unemployment rate as of this year? Cite sources.",
            "research",
            "research",
            "none",
        ),
        ("Write a short brief", "writing", "fast_general", "none"),
        ("Edit this paragraph", "editing", "fast_general", "none"),
        ("I miss someone, and I am unsure why.", "personal_reflection", "fast_general", "none"),
        ("Plan next week", "planning", "fast_general", "none"),
        ("Review this repository structure", "repository_execution", "fast_general", "none"),
        ("Explain what a mutex is in two sentences.", "general_reasoning", "cheap_local", "none"),
        ("Implement this function in src/parser.py", "coding", "fast_general", "staged"),
        (
            "Refactor this repository and apply the change",
            "repository_execution",
            "fast_general",
            "staged",
        ),
        ("Analyze this PDF file", "file_analysis", "fast_general", "none"),
        ("Create a multi-step mission", "multi_step_mission", "strong_reasoning", "none"),
        ("Code review this pull request", "repository_execution", "fast_general", "none"),
    )
    providers = [
        _cheap_local(
            capabilities=frozenset(
                {
                    "chat",
                    "coding",
                    "research",
                    "file_analysis",
                    "writing",
                    "planning",
                    "reflection",
                    "repository",
                    "decision_support",
                    "security",
                    "tools",
                    "data_analysis",
                    "creative",
                }
            )
        ),
        _strong_cloud(
            capabilities=frozenset(
                {
                    "chat",
                    "coding",
                    "research",
                    "file_analysis",
                    "writing",
                    "planning",
                    "reflection",
                    "repository",
                    "decision_support",
                    "security",
                    "tools",
                    "data_analysis",
                    "creative",
                }
            )
        ),
    ]
    for prompt, task, role, mutation in cases:
        plan = PersonalAIRouter().route(
            _request(prompt, cognitive_policy="implementation"),
            providers,
        )
        assert plan.task_class == task, prompt
        assert plan.capability_role == role, prompt
        assert plan.requirements.mutation_authority == mutation, prompt
        if task == "general_reasoning" and role in {"cheap_local", "fast_general"}:
            assert plan.record.verification_strategy != "tests_and_diff", prompt
            assert plan.record.autonomy_level == "answer_only", prompt


def test_subscription_backed_fast_model_is_not_scored_as_api_billed():
    local = _cheap_local()
    flash = _strong_cloud(
        model_id="gemini-flash",
        quality_tier="standard",
        cost_category="low",
        latency_category="low",
        capability_roles=frozenset({"fast_general"}),
        billing_classification="subscription_backed",
    )
    billed = _strong_cloud(
        provider_id="openai-api",
        model_id="paid-api",
        quality_tier="standard",
        cost_category="standard",
        billing_classification="api_billed",
        capability_roles=frozenset({"fast_general"}),
    )
    plan = PersonalAIRouter().route(
        _request("Explain the difference between TCP and UDP in three sentences."),
        [local, flash, billed],
    )
    flash_candidate = next(item for item in plan.candidates if item.model_id == "gemini-flash")
    billed_candidate = next(item for item in plan.candidates if item.model_id == "paid-api")
    assert flash_candidate.score_components["billing_fit"] > billed_candidate.score_components["billing_fit"]
    assert billed_candidate.score_components["billing_fit"] < 0
    assert plan.capability_role == "cheap_local"
    assert plan.record.selected_provider == "ollama"
