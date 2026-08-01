"""Deterministic, inspectable planning for personal-AI provider routes.

This module intentionally consumes immutable discovery snapshots.  Provider
discovery and execution remain separate concerns: routing produces a proposed
``RouteRecord`` plus its auditable alternatives and never invokes a runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Sequence

from .models import AISettings, PersonaVersion, RouteCandidate, RouteRecord

TaskClass = Literal[
    "security_review",
    "consequential_decision",
    "repository_review",
    "coding",
    "research",
    "writing",
    "planning",
    "creative",
    "reflection",
    "general_answer",
]
Complexity = Literal["simple", "moderate", "complex"]
PrivacyClassification = Literal["standard", "private", "sensitive"]
RiskClassification = Literal["green", "yellow", "red"]


@dataclass(frozen=True)
class ProviderSnapshot:
    """Provider-independent availability and capability evidence for one route.

    Discovery adapters can map their observed state into this immutable value.
    The router trusts no implied capability: every selection is limited to the
    fields present in the supplied snapshot.
    """

    provider_id: str
    model_id: str | None
    runtime_id: str | None
    provider_family: str
    available: bool
    local: bool
    requires_network: bool
    cost_category: Literal["free", "low", "standard", "high"] = "standard"
    quality_tier: Literal["weak", "standard", "strong"] = "standard"
    capabilities: frozenset[str] = field(default_factory=frozenset)
    tool_names: frozenset[str] = field(default_factory=frozenset)
    skill_names: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class RoutingRequest:
    """All explicit user and policy inputs needed to plan one route."""

    request_id: str
    conversation_id: str
    request_message_id: str
    prompt: str
    requested_persona_id: str
    settings: AISettings = field(default_factory=AISettings)
    local_only: bool | None = None
    provider_override: str | None = None
    model_override: str | None = None
    requested_tools: tuple[str, ...] = ()
    requested_skills: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoutingPlan:
    """A planned route and all considered candidates, ready for store persistence."""

    record: RouteRecord
    candidates: tuple[RouteCandidate, ...]
    task_class: TaskClass
    task_complexity: Complexity
    privacy_classification: PrivacyClassification
    risk_classification: RiskClassification


class NoEligibleRouteError(ValueError):
    """Raised rather than silently choosing a disallowed or unavailable route."""

    def __init__(self, candidates: Sequence[RouteCandidate]) -> None:
        self.candidates = tuple(candidates)
        super().__init__("no eligible provider route")


class PersonalAIRouter:
    """Scores immutable capability snapshots with transparent integer components."""

    def route(
        self,
        request: RoutingRequest,
        providers: Sequence[ProviderSnapshot],
        *,
        persona_version: PersonaVersion | None = None,
    ) -> RoutingPlan:
        task_class = classify_task(request.prompt)
        complexity = classify_complexity(request.prompt, task_class)
        privacy = classify_privacy(request.prompt, task_class)
        risk = classify_risk(request.prompt, task_class)
        route_id = f"route-{request.request_id}"
        local_only = (
            request.settings.local_only_default if request.local_only is None else request.local_only
        )
        candidates = [
            self._candidate(
                route_id=route_id,
                request=request,
                snapshot=snapshot,
                task_class=task_class,
                privacy=privacy,
                risk=risk,
                local_only=local_only,
                persona_version=persona_version,
            )
            for snapshot in providers
        ]
        ranked = _rank(candidates)
        eligible = [candidate for candidate in ranked if candidate.eligible]
        if not eligible:
            raise NoEligibleRouteError(ranked)

        selected = eligible[0]
        snapshot = next(
            item
            for item in providers
            if item.provider_id == selected.provider_id and item.model_id == selected.model_id
        )
        actual_persona_id, mismatch = _actual_persona(request, persona_version, snapshot)
        selected_tools = sorted(set(request.requested_tools) & snapshot.tool_names)
        selected_skills = _selected_skills(request, snapshot)
        reasons = list(selected.reasons)
        if request.provider_override:
            reasons.append("manual provider override honored")
        if request.model_override:
            reasons.append("manual model override honored")
        if mismatch:
            reasons.append(mismatch)

        record = RouteRecord(
            route_id=route_id,
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            request_message_id=request.request_message_id,
            task_class=task_class,
            task_complexity=complexity,
            selected_provider=snapshot.provider_id,
            selected_model=snapshot.model_id,
            selected_runtime=snapshot.runtime_id,
            requested_persona_id=request.requested_persona_id,
            requested_persona_version_id=(
                persona_version.persona_version_id if persona_version else None
            ),
            actual_persona_id=actual_persona_id,
            actual_persona_version_id=(
                persona_version.persona_version_id
                if actual_persona_id == request.requested_persona_id and persona_version
                else None
            ),
            selected_tools=selected_tools,
            selected_skills=selected_skills,
            privacy_classification=privacy,
            autonomy_level=_autonomy_level(risk),
            approval_requirements=_approval_requirements(risk),
            estimated_cost_category=snapshot.cost_category,
            expected_latency_category=_latency(complexity),
            route_score=selected.score,
            reasons=reasons,
            fallback_events=[],
            verification_strategy=_verification_strategy(task_class, request.settings),
            persona_provider_mismatch=mismatch,
            outcome_status="planned",
            metadata={
                "routing": "deterministic_snapshot_v1",
                "risk_classification": risk,
                "local_only": local_only,
            },
        )
        return RoutingPlan(
            record=record,
            candidates=tuple(ranked),
            task_class=task_class,
            task_complexity=complexity,
            privacy_classification=privacy,
            risk_classification=risk,
        )

    def _candidate(
        self,
        *,
        route_id: str,
        request: RoutingRequest,
        snapshot: ProviderSnapshot,
        task_class: TaskClass,
        privacy: PrivacyClassification,
        risk: RiskClassification,
        local_only: bool,
        persona_version: PersonaVersion | None,
    ) -> RouteCandidate:
        components = {
            "availability": 20 if snapshot.available else -100,
            "capability_fit": _capability_fit(snapshot, task_class),
            "cost_fit": _cost_fit(snapshot.cost_category, request.settings.cost_ceiling_category),
            "persona_affinity": _persona_affinity(snapshot, persona_version),
            "privacy_fit": _privacy_fit(snapshot, privacy),
            "risk_fit": _risk_fit(snapshot, task_class, risk),
            "tool_fit": _tool_fit(snapshot, request.requested_tools),
        }
        rejection = _rejection_reason(
            request=request,
            snapshot=snapshot,
            task_class=task_class,
            risk=risk,
            local_only=local_only,
        )
        reasons = [
            f"availability: {'available' if snapshot.available else 'unavailable'}",
            f"capability fit: {_capability_fit(snapshot, task_class)}",
            f"privacy fit: {_privacy_fit(snapshot, privacy)}",
            f"risk fit: {_risk_fit(snapshot, task_class, risk)}",
            f"cost fit: {_cost_fit(snapshot.cost_category, request.settings.cost_ceiling_category)}",
            f"persona affinity: {_persona_affinity(snapshot, persona_version)}",
            f"tool fit: {_tool_fit(snapshot, request.requested_tools)}",
        ]
        if rejection:
            reasons.append(f"rejected: {rejection}")
        return RouteCandidate(
            candidate_id=f"{route_id}-{snapshot.provider_id}-{snapshot.model_id or 'default'}",
            route_id=route_id,
            provider_id=snapshot.provider_id,
            model_id=snapshot.model_id,
            runtime_id=snapshot.runtime_id,
            rank=1,
            score=sum(components.values()),
            score_components=components,
            eligible=rejection is None,
            reasons=reasons,
            rejection_reason=rejection,
        )


def classify_task(prompt: str) -> TaskClass:
    """Classify a request by explicit keywords, from highest consequence first."""
    text = prompt.lower()
    if _contains(text, "security", "vulnerability", "credential", "secret", "api key", "token"):
        return "security_review"
    if _contains(text, "medical", "legal", "financial", "investment", "hire", "firing"):
        return "consequential_decision"
    if _contains(text, "repository", "repo", "codebase", "pull request", "git", "diff"):
        return "repository_review"
    if _contains(text, "implement", "code", "bug", "parser", "test", "refactor"):
        return "coding"
    if _contains(text, "research", "sources", "literature", "compare evidence"):
        return "research"
    if _contains(text, "write", "rewrite", "draft", "email"):
        return "writing"
    if _contains(text, "plan", "roadmap", "prioritize"):
        return "planning"
    if _contains(text, "brainstorm", "creative", "story", "ideas"):
        return "creative"
    if _contains(text, "reflect", "emotion", "feel", "relationship"):
        return "reflection"
    return "general_answer"


def classify_complexity(prompt: str, task_class: TaskClass) -> Complexity:
    text = prompt.lower()
    if task_class in {"security_review", "consequential_decision"} or _contains(
        text, "comprehensive", "architecture", "multiple", "system-wide"
    ):
        return "complex"
    if len(prompt.split()) <= 6 and task_class == "general_answer":
        return "simple"
    return "moderate"


def classify_privacy(prompt: str, task_class: TaskClass) -> PrivacyClassification:
    text = prompt.lower()
    if task_class == "security_review" or _contains(
        text, "password", "credential", "secret", "token", "medical record"
    ):
        return "sensitive"
    if task_class in {"repository_review", "consequential_decision", "reflection"} or _contains(
        text, "personal", "private", "financial"
    ):
        return "private"
    return "standard"


def classify_risk(prompt: str, task_class: TaskClass) -> RiskClassification:
    text = prompt.lower()
    if task_class in {"security_review", "consequential_decision"} or _contains(
        text, "deploy", "production", "delete", "send", "publish"
    ):
        return "red"
    if task_class in {"repository_review", "coding"}:
        return "yellow"
    return "green"


def _rank(candidates: Sequence[RouteCandidate]) -> list[RouteCandidate]:
    ordered = sorted(candidates, key=lambda item: (not item.eligible, -item.score, item.provider_id))
    return [candidate.model_copy(update={"rank": index}) for index, candidate in enumerate(ordered, 1)]


def _rejection_reason(
    *,
    request: RoutingRequest,
    snapshot: ProviderSnapshot,
    task_class: TaskClass,
    risk: RiskClassification,
    local_only: bool,
) -> str | None:
    if not snapshot.available:
        return "provider is unavailable"
    if local_only and (not snapshot.local or snapshot.requires_network):
        return "strict local-only policy excludes network/cloud provider"
    if request.provider_override and snapshot.provider_id != request.provider_override:
        return "excluded by manual provider override"
    if request.model_override and snapshot.model_id != request.model_override:
        return "model does not match manual override"
    required_capability = _task_capability(task_class)
    if required_capability not in snapshot.capabilities:
        return f"provider does not support required capability: {required_capability}"
    missing_tools = sorted(set(request.requested_tools) - snapshot.tool_names)
    if missing_tools:
        return f"provider does not support required tools: {', '.join(missing_tools)}"
    if task_class in {"security_review", "consequential_decision", "repository_review"} and (
        snapshot.quality_tier == "weak"
    ):
        return "serious task requires a strong model; weak local/free model rejected"
    if risk == "red" and snapshot.quality_tier == "weak":
        return "red-risk task requires a strong model"
    return None


def _task_capability(task_class: TaskClass) -> str:
    return {
        "security_review": "security",
        "consequential_decision": "decision_support",
        "repository_review": "repository",
        "coding": "coding",
        "research": "research",
        "writing": "writing",
        "planning": "planning",
        "creative": "creative",
        "reflection": "reflection",
        "general_answer": "chat",
    }[task_class]


def _capability_fit(snapshot: ProviderSnapshot, task_class: TaskClass) -> int:
    return 20 if _task_capability(task_class) in snapshot.capabilities else -40


def _cost_fit(cost_category: str, ceiling: str) -> int:
    base = {"free": 8, "low": 5, "standard": 2, "high": -4}[cost_category]
    ceiling_rank = {"free": 0, "low": 1, "standard": 2, "high": 3}
    cost_rank = {"free": 0, "low": 1, "standard": 2, "high": 3}
    return base if cost_rank[cost_category] <= ceiling_rank[ceiling] else base - 10


def _persona_affinity(snapshot: ProviderSnapshot, persona_version: PersonaVersion | None) -> int:
    if persona_version is None:
        return 0
    return persona_version.provider_affinities.get(snapshot.provider_id, 0)


def _privacy_fit(snapshot: ProviderSnapshot, privacy: PrivacyClassification) -> int:
    if privacy == "sensitive":
        return 16 if snapshot.local and not snapshot.requires_network else 4
    if privacy == "private":
        return 12 if snapshot.local and not snapshot.requires_network else 6
    return 8


def _risk_fit(snapshot: ProviderSnapshot, task_class: TaskClass, risk: RiskClassification) -> int:
    if task_class in {"security_review", "consequential_decision", "repository_review"}:
        return {"strong": 25, "standard": 10, "weak": -30}[snapshot.quality_tier]
    return 10 if risk != "red" or snapshot.quality_tier != "weak" else -20


def _tool_fit(snapshot: ProviderSnapshot, requested_tools: tuple[str, ...]) -> int:
    if not requested_tools:
        return 0
    return 12 if set(requested_tools).issubset(snapshot.tool_names) else -30


def _selected_skills(request: RoutingRequest, snapshot: ProviderSnapshot) -> list[str]:
    if request.settings.skill_permissions == "deny":
        return []
    return sorted(set(request.requested_skills) & snapshot.skill_names)


def _actual_persona(
    request: RoutingRequest,
    persona_version: PersonaVersion | None,
    snapshot: ProviderSnapshot,
) -> tuple[str, str | None]:
    if (
        persona_version is not None
        and persona_version.native_provider_family is not None
        and persona_version.native_provider_family != snapshot.provider_family
    ):
        return (
            "provider-native",
            "requested native persona expects "
            f"{persona_version.native_provider_family}; selected provider family is "
            f"{snapshot.provider_family}, so provider-native is an approximation",
        )
    return request.requested_persona_id, None


def _autonomy_level(risk: RiskClassification) -> str:
    return {"green": "answer_only", "yellow": "review_before_action", "red": "approval_required"}[risk]


def _approval_requirements(risk: RiskClassification) -> list[str]:
    return [] if risk == "green" else ["human review required before any execution"]


def _latency(complexity: Complexity) -> str:
    return {"simple": "low", "moderate": "standard", "complex": "high"}[complexity]


def _verification_strategy(task_class: TaskClass, settings: AISettings) -> str:
    if task_class == "security_review":
        return "security_review"
    if task_class == "consequential_decision":
        return "independent_review"
    if task_class == "repository_review":
        return "repository_review"
    if task_class == "coding":
        return "tests_and_diff"
    if settings.verification_preference == "strict":
        return "source_check"
    return "response_integrity"


def _contains(text: str, *terms: str) -> bool:
    return any(term in text for term in terms)
