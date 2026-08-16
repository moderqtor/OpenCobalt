"""Adaptive WorkGraph builder and dynamic graph manipulator."""

from __future__ import annotations

import hashlib

from .artifacts import EvaluationReport
from .models import (
    IntentContract,
    WorkGraph,
    WorkNode,
    WorkNodeType,
    _now_iso,
)


def _generate_graph_id(contract_id: str, timestamp: str) -> str:
    digest = hashlib.sha256(f"{contract_id}:{timestamp}".encode("utf-8")).hexdigest()[:12]
    return f"wgr-{digest}"


class WorkGraphPlanner:
    """Plans an adaptive WorkGraph from an IntentContract."""

    @classmethod
    def plan(cls, intent: IntentContract) -> WorkGraph:
        now = _now_iso()
        graph_id = _generate_graph_id(intent.contract_id, now)
        graph = WorkGraph(
            graph_id=graph_id,
            contract_id=intent.contract_id,
            status="active",
            iteration=1,
            created_at=now,
            updated_at=now,
        )

        has_creative_freedom = len(intent.open_creative_dimensions) > 0 or "roguelike" in intent.literal_request.lower() or "game" in intent.literal_request.lower()

        if has_creative_freedom:
            # Plan a multi-agent divergent tournament and dialectic before synthesis and coding

            # 1. Divergent Explorers (Parallel)
            node_exp_a = WorkNode(
                node_id="explore_mechanical_inversion",
                title="Divergent Exploration: Mechanical Inversion",
                work_type=WorkNodeType.EXPLORATION,
                required_capability="divergent_ideation",
                incentive_profile="mechanical_inversion",
                description="Explore a novel mechanical inversion of standard roguelike conventions, inverting core assumptions about resource scarcity, time, or spatial navigation.",
                dependencies=[],
                output_contract="CandidateConcept",
                evaluation_criteria=["novelty_score >= 7.0", "distinct_player_loop"],
            )

            node_exp_b = WorkNode(
                node_id="explore_emergent_simulation",
                title="Divergent Exploration: Emergent Simulation",
                work_type=WorkNodeType.EXPLORATION,
                required_capability="divergent_ideation",
                incentive_profile="emergent_simulation",
                description="Explore an unusual systemic simulation or ecological interaction model where systems collide to produce emergent gameplay.",
                dependencies=[],
                output_contract="CandidateConcept",
                evaluation_criteria=["systemic_depth", "emergent_interactions"],
            )

            graph.add_node(node_exp_a)
            graph.add_node(node_exp_b)

            # 2. Adversarial Critics (Parallel once explorers finish)
            node_crit_novelty = WorkNode(
                node_id="critique_novelty",
                title="Adversarial Critique: Novelty Attack",
                work_type=WorkNodeType.CRITIQUE,
                required_capability="critical_analysis",
                incentive_profile="novelty_critic",
                description="Attack candidate concepts for derivative clichés, common genre tropes, and lack of true mechanical originality.",
                dependencies=["explore_mechanical_inversion", "explore_emergent_simulation"],
                input_artifact_ids=["explore_mechanical_inversion", "explore_emergent_simulation"],
                output_contract="CritiqueReport",
                evaluation_criteria=["cliche_detection", "uniqueness_scoring"],
            )

            node_crit_fun = WorkNode(
                node_id="critique_fun_and_agency",
                title="Adversarial Critique: Decision Density & Agency",
                work_type=WorkNodeType.CRITIQUE,
                required_capability="critical_analysis",
                incentive_profile="fun_critic",
                description="Evaluate repeated decision quality, player agency, tension-release cycles, and tactical depth.",
                dependencies=["explore_mechanical_inversion", "explore_emergent_simulation"],
                input_artifact_ids=["explore_mechanical_inversion", "explore_emergent_simulation"],
                output_contract="CritiqueReport",
                evaluation_criteria=["decision_density", "risk_reward_balance"],
            )

            node_crit_contrarian = WorkNode(
                node_id="critique_contrarian",
                title="Adversarial Critique: Contrarian Defense",
                work_type=WorkNodeType.CRITIQUE,
                required_capability="critical_analysis",
                incentive_profile="contrarian_critic",
                description="Attack premature consensus, challenge majority assumptions, and defend the strongest unorthodox elements.",
                dependencies=["explore_mechanical_inversion", "explore_emergent_simulation"],
                input_artifact_ids=["explore_mechanical_inversion", "explore_emergent_simulation"],
                output_contract="CritiqueReport",
                evaluation_criteria=["anti_consensus_rigor", "unexamined_risks"],
            )

            node_crit_feasibility = WorkNode(
                node_id="critique_feasibility",
                title="Adversarial Critique: Implementation Feasibility",
                work_type=WorkNodeType.CRITIQUE,
                required_capability="critical_analysis",
                incentive_profile="feasibility_critic",
                description="Assess implementation feasibility, scoping boundaries, and technical complexity within available cognitive budget.",
                dependencies=["explore_mechanical_inversion", "explore_emergent_simulation"],
                input_artifact_ids=["explore_mechanical_inversion", "explore_emergent_simulation"],
                output_contract="CritiqueReport",
                evaluation_criteria=["scope_viability", "execution_complexity"],
            )

            graph.add_node(node_crit_novelty)
            graph.add_node(node_crit_fun)
            graph.add_node(node_crit_contrarian)
            graph.add_node(node_crit_feasibility)

            # 3. Creative Synthesis
            node_synth = WorkNode(
                node_id="synthesize_game_design",
                title="Design Synthesis & Specification",
                work_type=WorkNodeType.SYNTHESIS,
                required_capability="creative_synthesis",
                incentive_profile="design_synthesizer",
                description="Synthesize the winning mechanics and concepts into an authoritative design document, resolving critic objections against the IntentContract.",
                dependencies=[
                    "explore_mechanical_inversion",
                    "explore_emergent_simulation",
                    "critique_novelty",
                    "critique_fun_and_agency",
                    "critique_contrarian",
                    "critique_feasibility",
                ],
                input_artifact_ids=[
                    "explore_mechanical_inversion",
                    "explore_emergent_simulation",
                    "critique_novelty",
                    "critique_fun_and_agency",
                    "critique_contrarian",
                    "critique_feasibility",
                ],
                output_contract="SynthesizedDesign",
                evaluation_criteria=["constraint_compliance", "thematic_coherence", "critic_resolution"],
            )
            graph.add_node(node_synth)

            # 4. Implementation
            node_impl = WorkNode(
                node_id="implement_playable_prototype",
                title="Implementation: Playable Staged Prototype",
                work_type=WorkNodeType.IMPLEMENTATION,
                required_capability="coding_agent",
                incentive_profile="prototype_engineer",
                description="Implement a complete, self-contained, and interactive playable prototype in Python inside the staged workspace.",
                dependencies=["synthesize_game_design"],
                input_artifact_ids=["synthesize_game_design"],
                output_contract="ImplementationBundle",
                evaluation_criteria=["standalone_executable", "implements_design_spec", "runs_without_crash"],
            )
            graph.add_node(node_impl)

            # 5. Evaluation & Quality Gate
            node_eval = WorkNode(
                node_id="evaluate_gameplay_and_mechanics",
                title="Evaluation: Gameplay & Constraints Verification",
                work_type=WorkNodeType.EVALUATION,
                required_capability="evaluation_verification",
                incentive_profile="gameplay_evaluator",
                description="Execute automated simulation and unit checks to verify playable loop, win/loss resolution, and constraint adherence.",
                dependencies=["implement_playable_prototype"],
                input_artifact_ids=["implement_playable_prototype"],
                output_contract="EvaluationReport",
                evaluation_criteria=["playability_confirmed", "zero_crashes", "hard_constraints_verified"],
            )
            graph.add_node(node_eval)

        else:
            # Linear/structured work graph for tightly-specified requests
            node_plan = WorkNode(
                node_id="plan_architecture",
                title="Architecture & Implementation Planning",
                work_type=WorkNodeType.SYNTHESIS,
                required_capability="strong_reasoning",
                incentive_profile="system_architect",
                description="Decompose requirements into module specifications and test plans.",
                dependencies=[],
                output_contract="SynthesizedDesign",
            )
            node_impl = WorkNode(
                node_id="implement_code",
                title="Implementation in Staged Workspace",
                work_type=WorkNodeType.IMPLEMENTATION,
                required_capability="coding_agent",
                incentive_profile="software_engineer",
                description="Implement code according to architecture plan.",
                dependencies=["plan_architecture"],
                input_artifact_ids=["plan_architecture"],
                output_contract="ImplementationBundle",
            )
            node_eval = WorkNode(
                node_id="verify_test_suite",
                title="Verification & Quality Gate Check",
                work_type=WorkNodeType.EVALUATION,
                required_capability="evaluation_verification",
                incentive_profile="test_engineer",
                description="Run automated tests to verify zero regressions.",
                dependencies=["implement_code"],
                input_artifact_ids=["implement_code"],
                output_contract="EvaluationReport",
            )
            graph.add_node(node_plan)
            graph.add_node(node_impl)
            graph.add_node(node_eval)

        return graph

    @classmethod
    def apply_evidence_revision(
        cls,
        graph: WorkGraph,
        evaluation: EvaluationReport,
    ) -> list[WorkNode]:
        """Dynamically expands or mutates the graph when intermediate evaluation indicates weakness."""
        if not evaluation.revision_needed and not evaluation.issues_found:
            return []

        revision_count = sum(1 for n in graph.nodes.values() if n.work_type == WorkNodeType.REVISION) + 1
        node_rev_id = f"revise_weakness_round_{revision_count}"
        node_retest_id = f"retest_prototype_round_{revision_count}"

        rev_node = WorkNode(
            node_id=node_rev_id,
            title=f"Dynamic Revision: Resolve Flaws (Round {revision_count})",
            work_type=WorkNodeType.REVISION,
            required_capability="coding_agent",
            incentive_profile="refactor_specialist",
            description=f"Address identified issues: {'; '.join(evaluation.issues_found)}. Recommendations: {'; '.join(evaluation.recommended_revisions)}.",
            dependencies=["evaluate_gameplay_and_mechanics"],
            input_artifact_ids=["evaluate_gameplay_and_mechanics", "implement_playable_prototype"],
            output_contract="ImplementationBundle",
            evaluation_criteria=["issues_resolved", "preserves_core_mechanics"],
        )

        retest_node = WorkNode(
            node_id=node_retest_id,
            title=f"Evaluation: Re-Verify Revised Prototype (Round {revision_count})",
            work_type=WorkNodeType.EVALUATION,
            required_capability="evaluation_verification",
            incentive_profile="gameplay_evaluator",
            description="Re-run empirical playability and mechanics verification on revised build.",
            dependencies=[node_rev_id],
            input_artifact_ids=[node_rev_id],
            output_contract="EvaluationReport",
            evaluation_criteria=["zero_regressions", "playability_confirmed"],
        )

        graph.add_node(rev_node)
        graph.add_node(retest_node)
        graph.status = "revising"
        graph.iteration += 1
        graph.updated_at = _now_iso()

        return [rev_node, retest_node]
