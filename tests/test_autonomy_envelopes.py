"""Tests for autonomy envelopes and cognitive budgets."""

from __future__ import annotations

from opencobalt.core.autonomy_envelopes import (
    AUTONOMY_ENVELOPES,
    COGNITIVE_BUDGETS,
    AutonomyEnvelope,
    CognitiveBudget,
    get_autonomy_envelope,
    get_cognitive_budget,
)


def test_autonomy_envelopes_parse_and_validate() -> None:
    expected = {
        "observe",
        "plan",
        "dry_run",
        "sandbox_exec",
        "repo_autopilot",
        "pr_drafter",
        "autonomous_lab",
        "operator_yolo",
        "production_guarded",
    }

    assert set(AUTONOMY_ENVELOPES) == expected
    for envelope in AUTONOMY_ENVELOPES.values():
        parsed = AutonomyEnvelope.model_validate(envelope.model_dump())
        assert parsed.envelope_id in expected
        assert parsed.description
        assert parsed.receipt_requirements
        assert parsed.provenance_requirements


def test_cognitive_budgets_parse_and_validate() -> None:
    expected = {"low", "medium", "high", "xhigh", "research"}

    assert set(COGNITIVE_BUDGETS) == expected
    for budget in COGNITIVE_BUDGETS.values():
        parsed = CognitiveBudget.model_validate(budget.model_dump())
        assert parsed.budget_id in expected
        assert parsed.intended_use
        assert parsed.allowed_runtimes
        assert parsed.max_subagents >= 0
        assert parsed.max_recursion_depth >= 0
        assert parsed.max_runtime_iterations >= 1


def test_default_envelopes_do_not_grant_outward_authority() -> None:
    for envelope in AUTONOMY_ENVELOPES.values():
        assert envelope.allowed_deploy is False
        assert envelope.allowed_publish is False
        assert envelope.allowed_spend is False
        assert envelope.allowed_external_messages is False
        assert envelope.allowed_secret_auth_access is False


def test_operator_yolo_blocks_secrets_spend_deploy_messages_and_remote_actions() -> None:
    envelope = get_autonomy_envelope("operator_yolo")

    assert envelope.allowed_file_writes
    assert envelope.allowed_branch_creation is True
    assert envelope.allowed_commit is True
    assert envelope.allowed_push is False
    assert envelope.allowed_merge is False
    assert envelope.allowed_deploy is False
    assert envelope.allowed_publish is False
    assert envelope.allowed_spend is False
    assert envelope.allowed_external_messages is False
    assert envelope.allowed_secret_auth_access is False


def test_autonomous_lab_allows_high_local_autonomy_not_outward_actions() -> None:
    envelope = get_autonomy_envelope("autonomous_lab")

    assert "repo" in envelope.allowed_file_reads
    assert "repo" in envelope.allowed_file_writes
    assert envelope.allowed_subprocess_execution == "policy_gated_local"
    assert envelope.default_cognitive_budget == "xhigh"
    assert envelope.allowed_push is False
    assert envelope.allowed_merge is False
    assert envelope.allowed_deploy is False
    assert envelope.allowed_publish is False
    assert envelope.allowed_spend is False
    assert envelope.allowed_external_messages is False
    assert envelope.allowed_secret_auth_access is False


def test_research_budget_allows_research_without_runtime_or_authority_grants() -> None:
    budget = get_cognitive_budget("research")

    assert budget.web_research_appropriate is True
    assert budget.cross_agent_debate_enabled is True
    assert budget.external_runtimes_may_be_invoked is False
