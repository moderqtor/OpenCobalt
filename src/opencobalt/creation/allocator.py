"""Resource and capability allocator mapping provider-neutral WorkGraph nodes to runtimes."""

from __future__ import annotations

import shutil
from typing import Any

from .models import WorkNode


class CapabilityAllocator:
    """Allocates provider-neutral work nodes to eligible runtimes under active resource constraints."""

    def __init__(self) -> None:
        self.antigravity_available = shutil.which("agy") is not None
        # Quota constraint test: Codex and Cursor are documented as exhausted
        self.codex_available = False  # Quota exhausted
        self.cursor_available = False  # Quota exhausted

    def allocate_executor(self, node: WorkNode) -> str:
        """Determines the concrete runtime adapter for a WorkNode."""
        if self.antigravity_available:
            return "google-antigravity-broker"
        return "local-deterministic"

    def build_node_prompt(self, node: WorkNode, intent_literal: str, input_artifacts: dict[str, Any]) -> str:
        """Constructs a role-specific and incentive-aligned prompt for a WorkNode."""
        base_context = (
            f"OVERARCHING HUMAN INTENT:\n\"{intent_literal}\"\n\n"
            f"WORK OBJECTIVE:\n{node.description}\n\n"
            f"INPUT ARTIFACTS:\n"
        )
        for art_id, art_data in input_artifacts.items():
            base_context += f"--- Artifact [{art_id}] ---\n{art_data}\n\n"

        if node.incentive_profile == "mechanical_inversion":
            return (
                f"{base_context}\n"
                "ROLE & INCENTIVE: You are EXPLORER A (Mechanical Inversion Specialist).\n"
                "Your objective is to invent a radical mechanical inversion of typical roguelike tropes.\n"
                "Do NOT propose a standard dungeon crawler with HP potions and simple attack rolls.\n"
                "Invert core assumptions: what if the player controls the dungeon or environment? What if light is both health and sight? What if taking damage alters the laws of physics?\n"
                "Return a structured JSON object adhering to the CandidateConcept schema with fields: title, tagline, thematic_premise, core_mechanical_inversion, ecosystem_dynamics, player_decision_loop, risk_and_permadeath_model, feasibility_notes."
            )

        elif node.incentive_profile == "emergent_simulation":
            return (
                f"{base_context}\n"
                "ROLE & INCENTIVE: You are EXPLORER B (Emergent Simulation & Systems Specialist).\n"
                "Your objective is to design a roguelike driven by interacting ecological, elemental, or systemic rules.\n"
                "Focus on emergent behavior where systems interact without scripted encounters (e.g. food webs, temperature gradients, sound propagation, predator/prey dynamics).\n"
                "Return a structured JSON object adhering to the CandidateConcept schema with fields: title, tagline, thematic_premise, core_mechanical_inversion, ecosystem_dynamics, player_decision_loop, risk_and_permadeath_model, feasibility_notes."
            )

        elif node.incentive_profile == "novelty_critic":
            return (
                f"{base_context}\n"
                "ROLE & INCENTIVE: You are the NOVELTY CRITIC (Adversarial Cliché Hunter).\n"
                "Your job is to ATTACK candidate concepts for derivativeness, clichés, and superficial gimmicks.\n"
                "Identify where these concepts are secretly just reskinned NetHack/Brogue or standard RPG tropes.\n"
                "Score novelty from 0.0 to 10.0 and identify exact vulnerabilities and suggested fixes.\n"
                "Return a structured JSON object adhering to the CritiqueReport schema."
            )

        elif node.incentive_profile == "fun_critic":
            return (
                f"{base_context}\n"
                "ROLE & INCENTIVE: You are the FUN & AGENCY CRITIC (Decision Density Analyst).\n"
                "Ignore novelty hype. Evaluate whether the moment-to-moment game loop produces interesting tactical decisions.\n"
                "Does the player have meaningful agency, or does RNG dictate the outcome? Is there high tension and risk/reward?\n"
                "Score decision density from 0.0 to 10.0 and return a CritiqueReport JSON object."
            )

        elif node.incentive_profile == "contrarian_critic":
            return (
                f"{base_context}\n"
                "ROLE & INCENTIVE: You are the CONTRARIAN CRITIC (Anti-Consensus Inquisitor).\n"
                "Your mandate is to challenge the emerging majority consensus among the explorers and critics.\n"
                "Defend the weirdest, most rejected unorthodox ideas. Highlight unseen catastrophic risks in the safe options.\n"
                "Return a CritiqueReport JSON object."
            )

        elif node.incentive_profile == "feasibility_critic":
            return (
                f"{base_context}\n"
                "ROLE & INCENTIVE: You are the FEASIBILITY CRITIC (Execution Scope Reviewer).\n"
                "Evaluate whether this design can be cleanly implemented as a robust, bug-free, self-contained playable prototype.\n"
                "Flag over-scoped simulation or excessive complexity that would fail in a compact implementation.\n"
                "Return a CritiqueReport JSON object."
            )

        elif node.incentive_profile == "design_synthesizer":
            return (
                f"{base_context}\n"
                "ROLE & INCENTIVE: You are the DESIGN SYNTHESIZER.\n"
                "Your job is to synthesize an authoritative, cohesive game design specification.\n"
                "Incorporate the winning mechanical inversion and emergent systems while directly addressing and resolving the vulnerabilities flagged by the critics.\n"
                "Return a SynthesizedDesign JSON object."
            )

        elif node.incentive_profile == "prototype_engineer":
            return (
                f"{base_context}\n"
                "ROLE & INCENTIVE: You are the PROTOTYPE SOFTWARE ENGINEER.\n"
                "Implement a complete, standalone, playable terminal-based roguelike in Python matching the SynthesizedDesign.\n"
                "It must run directly with python3, feature full game loop, procedural generation, enemy AI/ecosystem, HUD display, and win/loss conditions.\n"
                "Return an ImplementationBundle JSON object containing the complete runnable code files."
            )

        elif node.incentive_profile == "gameplay_evaluator":
            return (
                f"{base_context}\n"
                "ROLE & INCENTIVE: You are the GAMEPLAY & QUALITY EVALUATOR.\n"
                "Test and verify the playable prototype. Verify that the game loop executes, mechanics function as intended, and constraints are preserved.\n"
                "Return an EvaluationReport JSON object."
            )

        return f"{base_context}\nExecute the work according to specifications."
