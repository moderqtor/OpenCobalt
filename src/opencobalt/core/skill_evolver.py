"""Self-improving skill loop -- STUB, deferred to next session.

Full implementation requires:
- SQLite skill_evolutions table migration
- Score-based comparison via local eval prompt (Ollama worker tier)
- Version management: skill_name_vN.py side-by-side storage
- opencobalt skills evolve SKILLNAME [--task ...] [--auto-promote] [--rollback N]
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EvolutionResult:
    skill_name: str
    version: int
    current_score: float
    new_score: float
    promoted: bool
    notes: str
    diff: str = ""


class SkillEvolver:
    """Evaluate a skill against a test task and promote if improved.

    TODO: implement full evolution loop -- see docs for spec.
    """

    def evolve(
        self,
        skill_name: str,
        test_task: str = "",  # noqa: ARG002
        auto_promote: bool = False,  # noqa: ARG002
    ) -> EvolutionResult:
        return EvolutionResult(
            skill_name=skill_name,
            version=1,
            current_score=0.0,
            new_score=0.0,
            promoted=False,
            notes="Skill evolution not yet implemented. Deferred to next session.",
        )

    def rollback(self, skill_name: str, version: int = 0) -> bool:  # noqa: ARG002
        """Restore an earlier skill version -- TODO: implement."""
        return False

    def history(self, skill_name: str) -> list[dict]:  # noqa: ARG002
        """Return evolution history for a skill -- TODO: implement."""
        return []
