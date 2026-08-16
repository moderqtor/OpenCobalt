"""Structured artifact models exchanged across WorkGraph nodes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass
class CandidateConcept:
    """A divergent creative concept pitched by an exploratory agent."""

    concept_id: str
    title: str
    tagline: str
    thematic_premise: str
    core_mechanical_inversion: str
    ecosystem_dynamics: str
    player_decision_loop: str
    risk_and_permadeath_model: str
    feasibility_notes: str
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CandidateConcept:
        return cls(**data)


@dataclass
class CritiqueReport:
    """An adversarial evaluation from a specialized critic role."""

    critic_role: str
    target_concept_id: str
    score: float
    primary_strengths: list[str] = field(default_factory=list)
    vulnerabilities_and_flaws: list[str] = field(default_factory=list)
    contrarian_dissent: str = ""
    suggested_revisions: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CritiqueReport:
        return cls(**data)


@dataclass
class SynthesizedDesign:
    """The authoritative design specification synthesized from exploration & critique."""

    design_id: str
    game_title: str
    thematic_premise: str
    winning_concept_sources: list[str]
    synthesis_rationale: str
    critique_resolutions: list[str]
    core_systems: dict[str, Any]
    prototype_architecture: dict[str, Any]
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SynthesizedDesign:
        return cls(**data)


@dataclass
class ImplementationBundle:
    """The staged runnable implementation files and execution metadata."""

    bundle_id: str
    design_id: str
    files: dict[str, str] = field(default_factory=dict)
    entrypoint: str = "main.py"
    instructions: str = ""
    summary: str = ""
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImplementationBundle:
        return cls(**data)


@dataclass
class EvaluationReport:
    """Empirical and mechanical verification of the generated prototype."""

    evaluation_id: str
    bundle_id: str
    mechanics_verified: list[str] = field(default_factory=list)
    playability_test_passed: bool = True
    decision_density_score: float = 8.0
    novelty_score: float = 8.0
    issues_found: list[str] = field(default_factory=list)
    revision_needed: bool = False
    recommended_revisions: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvaluationReport:
        return cls(**data)
