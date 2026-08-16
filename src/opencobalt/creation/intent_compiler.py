"""Intent compiler translating human desire into a structured IntentContract."""

from __future__ import annotations

import hashlib
import re

from .models import IntentContract, IntentItem, IntentSource, _now_iso


def _generate_intent_id(raw_request: str, timestamp: str) -> str:
    digest = hashlib.sha256(f"{raw_request}:{timestamp}".encode("utf-8")).hexdigest()[:12]
    return f"intc-{digest}"


class IntentCompiler:
    """Compiles raw user prompt into an immutable IntentContract."""

    @classmethod
    def compile(
        cls,
        raw_request: str,
        *,
        autonomy: str = "autonomous_lab",
        budget: str = "4h",
        max_iterations: int = 10,
        max_workers: int = 4,
        project_path: str | None = None,
    ) -> IntentContract:
        cleaned = raw_request.strip()
        now = _now_iso()
        contract_id = _generate_intent_id(cleaned, now)

        hard_constraints: list[IntentItem] = []
        user_preferences: list[IntentItem] = []
        inferred_objectives: list[IntentItem] = []
        inferred_assumptions: list[IntentItem] = []
        open_dimensions: list[IntentItem] = []

        # 1. Parse explicit negative/hard constraints
        # Look for explicit negation patterns: "no crafting", "without combat", "never ...", "must not ...", "strictly ..."
        negation_patterns = [
            r"\b(?:no|without|never|zero)\s+([a-zA-Z0-9_\-\s]+?)(?:,|\.|$|;|and\b)",
            r"\bmust\s+not\s+([a-zA-Z0-9_\-\s]+?)(?:,|\.|$|;|and\b)",
            r"\bstrictly\s+([a-zA-Z0-9_\-\s]+?)(?:,|\.|$|;|and\b)",
        ]
        for pat in negation_patterns:
            for match in re.finditer(pat, cleaned, re.IGNORECASE):
                phrase = match.group(0).strip(" ,.;")
                if phrase and len(phrase) > 3:
                    hard_constraints.append(
                        IntentItem(
                            text=f"Explicit constraint: {phrase}",
                            source=IntentSource.EXPLICIT_USER,
                            category="constraint",
                        )
                    )

        # Look for explicit positive constraints: "must be ...", "must include ...", "only in Python"
        must_patterns = [
            r"\bmust\s+(?:be|include|have|use)\s+([a-zA-Z0-9_\-\s]+?)(?:,|\.|$|;|and\b)",
            r"\bonly\s+(?:in|using)\s+([a-zA-Z0-9_\-\s]+?)(?:,|\.|$|;|and\b)",
        ]
        for pat in must_patterns:
            for match in re.finditer(pat, cleaned, re.IGNORECASE):
                phrase = match.group(0).strip(" ,.;")
                if phrase and len(phrase) > 3:
                    hard_constraints.append(
                        IntentItem(
                            text=f"Explicit constraint: {phrase}",
                            source=IntentSource.EXPLICIT_USER,
                            category="constraint",
                        )
                    )

        # 2. Parse explicit preferences
        preference_patterns = [
            r"\b(?:emphasis\s+on|focus\s+on|prefer|preferably|with\s+a\s+strong\s+emphasis\s+on)\s+([a-zA-Z0-9_\-\s]+?)(?:,|\.|$|;|and\b)",
            r"\b(?:surreal|atmospheric|retro|minimalist|fast-paced|strategic|humorous|dark)\b",
        ]
        for pat in preference_patterns:
            for match in re.finditer(pat, cleaned, re.IGNORECASE):
                phrase = match.group(0).strip(" ,.;")
                if phrase and len(phrase) > 2:
                    user_preferences.append(
                        IntentItem(
                            text=f"User preference: {phrase}",
                            source=IntentSource.EXPLICIT_USER,
                            category="style_preference",
                        )
                    )

        # 3. Domain classification and inference (e.g. Roguelike / Game / Software / Research)
        lower_req = cleaned.lower()
        if "roguelike" in lower_req or "game" in lower_req or "video game" in lower_req:
            # Roguelike domain inference
            inferred_objectives.extend(
                [
                    IntentItem(
                        text="Engaging core turn/run loop with meaningful high-stakes decisions",
                        source=IntentSource.INFERRED_OPENCOBALT,
                        category="core_mechanics",
                    ),
                    IntentItem(
                        text="Procedural generation with emergent interactions and distinct run variety",
                        source=IntentSource.INFERRED_OPENCOBALT,
                        category="systems",
                    ),
                    IntentItem(
                        text="Functional, interactive, and playable software prototype with self-contained execution",
                        source=IntentSource.INFERRED_OPENCOBALT,
                        category="deliverable",
                    ),
                    IntentItem(
                        text="Permadeath and run progression mechanics with clear win/loss state resolution",
                        source=IntentSource.INFERRED_OPENCOBALT,
                        category="game_loop",
                    ),
                ]
            )
            inferred_assumptions.extend(
                [
                    IntentItem(
                        text="Prototype should run standalone locally with standard dependencies",
                        source=IntentSource.INFERRED_OPENCOBALT,
                        category="runtime_environment",
                    ),
                    IntentItem(
                        text="Decision density and tactical depth prioritize interesting tradeoffs over reflexive twitch skill",
                        source=IntentSource.INFERRED_OPENCOBALT,
                        category="design_philosophy",
                    ),
                ]
            )
            open_dimensions.extend(
                [
                    IntentItem(
                        text="Thematic setting and narrative framing (e.g. abyssal deep-sea, quantum chronomancy, symbiotic biopunk)",
                        source=IntentSource.INFERRED_OPENCOBALT,
                        category="thematic_freedom",
                    ),
                    IntentItem(
                        text="Core mechanical inversion or signature hook distinguishing from generic dungeon crawlers",
                        source=IntentSource.INFERRED_OPENCOBALT,
                        category="mechanical_freedom",
                    ),
                    IntentItem(
                        text="Presentation and UI style (e.g. rich ANSI/curses terminal interface or lightweight web/canvas)",
                        source=IntentSource.INFERRED_OPENCOBALT,
                        category="presentation_freedom",
                    ),
                    IntentItem(
                        text="Ecosystem and enemy behavior dynamics (e.g. food web predation, sensory propagation, environmental hazards)",
                        source=IntentSource.INFERRED_OPENCOBALT,
                        category="systemic_freedom",
                    ),
                ]
            )
        else:
            # General software/system intent inference
            inferred_objectives.extend(
                [
                    IntentItem(
                        text="Robust architecture meeting declared functional requirements",
                        source=IntentSource.INFERRED_OPENCOBALT,
                        category="architecture",
                    ),
                    IntentItem(
                        text="Verified runnable implementation with automated test coverage",
                        source=IntentSource.INFERRED_OPENCOBALT,
                        category="implementation",
                    ),
                ]
            )
            open_dimensions.extend(
                [
                    IntentItem(
                        text="Internal module structure and design patterns",
                        source=IntentSource.INFERRED_OPENCOBALT,
                        category="implementation_freedom",
                    ),
                ]
            )

        quality_criteria = {
            "novelty_score": 7.0,
            "decision_density": 7.5,
            "feasibility_score": 8.0,
            "thematic_coherence": 7.0,
            "verification_status": "tests_passing_and_playable",
        }

        budget_spec = {
            "wall_clock_budget": budget,
            "max_iterations": max_iterations,
            "max_workers": max_workers,
            "stop_conditions": [
                "all_work_nodes_completed",
                "prototype_verified_playable",
                "max_iterations_exhausted",
                "diminishing_marginal_improvement",
            ],
        }

        return IntentContract(
            contract_id=contract_id,
            literal_request=cleaned,
            hard_constraints=hard_constraints,
            user_preferences=user_preferences,
            inferred_objectives=inferred_objectives,
            inferred_assumptions=inferred_assumptions,
            open_creative_dimensions=open_dimensions,
            quality_criteria=quality_criteria,
            authority_level=autonomy,
            budget=budget_spec,
            created_at=now,
            metadata={"project_path": project_path} if project_path else {},
        )
