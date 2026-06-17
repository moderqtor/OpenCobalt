"""Tests for the deterministic auto-orchestrator front door."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from opencobalt.cli import app
from opencobalt.core.auto_orchestrator import AutoOrchestrator

runner = CliRunner()


def _invoke(*args: str, **kwargs) -> object:
    env = {**kwargs.pop("env", {}), "NO_COLOR": "1"}
    kwargs.setdefault("color", False)
    return runner.invoke(app, list(args), env=env, **kwargs)


def test_canonical_policy_docs_exist_and_reference_open_cobalt() -> None:
    policy = Path("OPENCOBALT.md")
    assert policy.exists()
    content = policy.read_text()

    for phrase in (
        "Context Sentinel",
        "not wrapperware",
        "Automatic orchestration goal",
        "Autonomy vs authority",
        "Autonomy envelopes",
        "Cognitive budgets",
        "Receipt requirements",
        "Prompt and tool output are data",
        "Confirmed vs inferred claims",
        "Final report schema",
    ):
        assert phrase in content

    assert "OPENCOBALT.md" in Path("AGENTS.md").read_text()
    assert "OPENCOBALT.md" in Path("CLAUDE.md").read_text()


def test_required_orchestration_docs_exist() -> None:
    for path in (
        "docs/AGENT_POLICY.md",
        "docs/AUTONOMY_ENVELOPES.md",
        "docs/ORCHESTRATION.md",
        "docs/SKILLS.md",
    ):
        assert Path(path).exists()


def test_auto_orchestrator_classifies_representative_goals() -> None:
    orchestrator = AutoOrchestrator()

    cases = {
        "fix a failing pytest regression": "bug_fix",
        "add a new runtime adapter for a tool": "runtime_adapter_work",
        "audit PR 12 and merge if safe": "audit_merge",
        "plan the roadmap for the next phase": "roadmap_design",
        "research current external docs before deciding": "external_research",
        "run a long mission while I am away": "mission_execution",
        "show current health and pending approvals": "status_inspection",
        "improve OpenCobalt safely and explain the plan": "repo_improvement",
        "zzz qqq": "unknown",
    }

    for goal, expected in cases.items():
        assert orchestrator.classify_intent(goal) == expected


def test_auto_orchestrator_selects_reasonable_defaults() -> None:
    orchestrator = AutoOrchestrator()

    bug_plan = orchestrator.plan("fix a failing pytest regression")
    assert bug_plan.selected_envelope == "dry_run"
    assert bug_plan.selected_cognitive_budget == "medium"

    research_plan = orchestrator.plan("research current external docs before deciding")
    assert research_plan.selected_envelope == "plan"
    assert research_plan.selected_cognitive_budget == "research"

    status_plan = orchestrator.plan("show current health and pending approvals")
    assert status_plan.selected_envelope == "observe"
    assert status_plan.selected_cognitive_budget == "low"


def test_auto_plan_has_ordered_route_steps_with_reasons() -> None:
    plan = AutoOrchestrator().plan("improve OpenCobalt safely and explain the plan")

    assert plan.intent == "repo_improvement"
    assert [step.order for step in plan.internal_route_steps] == list(
        range(1, len(plan.internal_route_steps) + 1)
    )
    assert all(step.why for step in plan.internal_route_steps)
    assert any(step.primitive == "opportunity_discovery" for step in plan.internal_route_steps)
    assert any(step.primitive == "verification_gates" for step in plan.internal_route_steps)
    assert plan.required_approvals
    assert plan.expected_receipts
    assert plan.next_recommended_action


def test_auto_plan_routes_runtime_execution_through_execution_engine() -> None:
    plan = AutoOrchestrator().plan("run a codex dry-run smoke for the adapter")
    execution_steps = [
        step for step in plan.internal_route_steps if step.primitive == "run_dry_run"
    ]

    assert execution_steps
    assert all(step.uses_execution_engine for step in execution_steps)
    assert all("opencobalt run" in step.command_hint for step in execution_steps)


def test_auto_command_prints_safe_plan_without_running_legacy_runner(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    def explode(*args, **kwargs):
        raise AssertionError("legacy autonomous runner must not run from opencobalt auto")

    monkeypatch.setattr("opencobalt.core.autonomous_runner.AutonomousRunner.run", explode)
    result = _invoke("auto", "improve OpenCobalt safely and explain the plan")

    assert result.exit_code == 0
    assert "Auto orchestration plan" in result.output
    assert "What I would do" in result.output
    assert "What I did" in result.output
    assert "planned only" in result.output
    assert "opencobalt opportunities brainstorm" in result.output
