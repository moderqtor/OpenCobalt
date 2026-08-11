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
    "general_reasoning",
    "personal_reflection",
    "repository_execution",
    "coding",
    "research",
    "writing",
    "editing",
    "file_analysis",
    "planning",
    "creative_ideation",
    "data_analysis",
    "tool_operation",
    "multi_step_mission",
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
    latency_category: Literal["low", "standard", "high"] = "standard"
    historical_success_signal: int = 0
    quota_pressure: int = 0
    provider_priority: int = 0

    def __post_init__(self) -> None:
        """Reject unbounded evidence while normalizing capability collections."""
        if not -10 <= self.historical_success_signal <= 10:
            raise ValueError("historical_success_signal must be between -10 and 10")
        if not 0 <= self.quota_pressure <= 10:
            raise ValueError("quota_pressure must be between 0 and 10")
        if not -10 <= self.provider_priority <= 10:
            raise ValueError("provider_priority must be between -10 and 10")
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        object.__setattr__(self, "tool_names", frozenset(self.tool_names))
        object.__setattr__(self, "skill_names", frozenset(self.skill_names))


@dataclass(frozen=True)
class RoutingRequest:
    """All explicit user and policy inputs needed to plan one route."""

    request_id: str
    conversation_id: str
    request_message_id: str
    prompt: str
    requested_persona_id: str
    settings: AISettings = field(default_factory=AISettings)
    privacy_mode: PrivacyClassification | None = None
    cognitive_policy: str = "fast_answer"
    reasoning_effort: Literal["low", "medium", "high", "xhigh"] = "medium"
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
        task_class = classify_task(request.prompt, request.cognitive_policy)
        complexity = classify_complexity(
            request.prompt, task_class, request.cognitive_policy, request.reasoning_effort
        )
        privacy = classify_privacy(
            request.prompt,
            task_class,
            request.privacy_mode,
            request.settings.privacy_policy,
        )
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
            approval_requirements=approval_requirements(risk),
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
                "privacy_mode": request.privacy_mode,
                "privacy_policy": request.settings.privacy_policy,
                "cognitive_policy": request.cognitive_policy,
                "reasoning_effort": request.reasoning_effort,
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
            "latency_fit": _latency_fit(snapshot, request),
            "historical_success": snapshot.historical_success_signal,
            "quota_pressure": -snapshot.quota_pressure,
            "provider_priority": snapshot.provider_priority,
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
            f"latency fit: {_latency_fit(snapshot, request)}",
            f"historical success: {snapshot.historical_success_signal}",
            f"quota pressure: {-snapshot.quota_pressure}",
            f"provider priority: {snapshot.provider_priority}",
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


def classify_task(prompt: str, cognitive_policy: str = "fast_answer") -> TaskClass:
    """Classify a request by explicit keywords, from highest consequence first."""
    text = prompt.lower()
    if _contains(text, "security", "vulnerability", "credential", "secret", "api key", "token"):
        return "security_review"
    if _contains(text, "medical", "legal", "financial", "investment", "hire", "firing"):
        return "consequential_decision"
    if _contains(text, "multi-step", "multi step", "mission"):
        return "multi_step_mission"
    if _contains(text, "csv", "dataset", "spreadsheet", "data analysis"):
        return "data_analysis"
    if _contains(text, "pdf", "file", "document", "log"):
        return "file_analysis"
    if _contains(text, "repository", "repo", "codebase", "pull request", "git", "diff"):
        return "repository_execution"
    if _contains(text, "run", "execute", "use tool", "call tool"):
        return "tool_operation"
    if _contains(text, "implement", "code", "bug", "parser", "test", "refactor"):
        return "coding"
    if _contains(text, "research", "sources", "literature", "compare evidence"):
        return "research"
    if _contains(text, "edit", "revise", "proofread"):
        return "editing"
    if _contains(text, "write", "rewrite", "draft", "email"):
        return "writing"
    if _contains(text, "plan", "roadmap", "prioritize"):
        return "planning"
    if _contains(text, "brainstorm", "creative", "story", "ideas"):
        return "creative_ideation"
    if _contains(text, "reflect", "emotion", "feel", "relationship"):
        return "personal_reflection"
    return {
        "implementation": "coding",
        "research_synthesis": "research",
        "creative_divergence": "creative_ideation",
        "emotional_reflection": "personal_reflection",
        "decision_support": "planning",
    }.get(cognitive_policy, "general_reasoning")


def classify_complexity(
    prompt: str,
    task_class: TaskClass,
    cognitive_policy: str = "fast_answer",
    reasoning_effort: str = "medium",
) -> Complexity:
    text = prompt.lower()
    if reasoning_effort in {"high", "xhigh"}:
        return "complex"
    if task_class in {"security_review", "consequential_decision", "multi_step_mission"} or _contains(
        text, "comprehensive", "architecture", "multiple", "system-wide"
    ):
        return "complex"
    if cognitive_policy in {"deep_analysis", "skeptical_review", "implementation", "research_synthesis"}:
        return "moderate"
    if len(prompt.split()) <= 6 and task_class == "general_reasoning":
        return "simple"
    return "moderate"


def classify_privacy(
    prompt: str,
    task_class: TaskClass,
    privacy_mode: PrivacyClassification | None = None,
    settings_privacy: PrivacyClassification = "standard",
) -> PrivacyClassification:
    text = prompt.lower()
    if task_class == "security_review" or _contains(
        text, "password", "credential", "secret", "token", "medical record"
    ):
        return "sensitive"
    if task_class in {"repository_execution", "consequential_decision", "personal_reflection"} or _contains(
        text, "personal", "private", "financial"
    ):
        inferred: PrivacyClassification = "private"
    else:
        inferred = "standard"
    return max((inferred, privacy_mode or "standard", settings_privacy), key=_privacy_rank)


def classify_risk(prompt: str, task_class: TaskClass) -> RiskClassification:
    text = prompt.lower()
    if task_class in {"security_review", "consequential_decision"} or _contains(
        text, "deploy", "production", "delete", "send", "publish"
    ):
        return "red"
    if task_class in {"repository_execution", "coding", "tool_operation", "multi_step_mission"}:
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
    if _cost_rank(snapshot.cost_category) > _cost_rank(request.settings.cost_ceiling_category):
        return (
            f"provider cost category '{snapshot.cost_category}' exceeds configured ceiling "
            f"'{request.settings.cost_ceiling_category}'"
        )
    if task_class in {"security_review", "consequential_decision", "repository_execution"} and (
        snapshot.quality_tier == "weak"
    ):
        return "serious task requires a strong model; weak local/free model rejected"
    if task_class == "coding" and complexity_is_complex(request, task_class) and snapshot.quality_tier == "weak":
        return "complex implementation requires a strong model"
    if risk == "red" and snapshot.quality_tier == "weak":
        return "red-risk task requires a strong model"
    return None


def _task_capability(task_class: TaskClass) -> str:
    return {
        "security_review": "security",
        "consequential_decision": "decision_support",
        "repository_execution": "repository",
        "coding": "coding",
        "research": "research",
        "writing": "writing",
        "editing": "writing",
        "file_analysis": "file_analysis",
        "planning": "planning",
        "creative_ideation": "creative",
        "data_analysis": "data_analysis",
        "tool_operation": "tools",
        "multi_step_mission": "planning",
        "personal_reflection": "reflection",
        "general_reasoning": "chat",
    }[task_class]


def _capability_fit(snapshot: ProviderSnapshot, task_class: TaskClass) -> int:
    return 20 if _task_capability(task_class) in snapshot.capabilities else -40


def _cost_fit(cost_category: str, ceiling: str) -> int:
    base = {"free": 8, "low": 5, "standard": 2, "high": -4}[cost_category]
    return base if _cost_rank(cost_category) <= _cost_rank(ceiling) else base - 10


def _cost_rank(value: str) -> int:
    return {"free": 0, "low": 1, "standard": 2, "high": 3}[value]


def _privacy_rank(value: PrivacyClassification) -> int:
    return {"standard": 0, "private": 1, "sensitive": 2}[value]


def _persona_affinity(snapshot: ProviderSnapshot, persona_version: PersonaVersion | None) -> int:
    if persona_version is None:
        return 0
    identities = (snapshot.provider_id, snapshot.runtime_id, snapshot.provider_family)
    matches = [
        persona_version.provider_affinities[identity]
        for identity in identities
        if identity is not None and identity in persona_version.provider_affinities
    ]
    return max(matches) if matches else 0


def _privacy_fit(snapshot: ProviderSnapshot, privacy: PrivacyClassification) -> int:
    if privacy == "sensitive":
        return 16 if snapshot.local and not snapshot.requires_network else 4
    if privacy == "private":
        return 12 if snapshot.local and not snapshot.requires_network else 6
    return 8


def _risk_fit(snapshot: ProviderSnapshot, task_class: TaskClass, risk: RiskClassification) -> int:
    if task_class in {"security_review", "consequential_decision", "repository_execution"}:
        return {"strong": 25, "standard": 10, "weak": -30}[snapshot.quality_tier]
    return 10 if risk != "red" or snapshot.quality_tier != "weak" else -20


def _tool_fit(snapshot: ProviderSnapshot, requested_tools: tuple[str, ...]) -> int:
    if not requested_tools:
        return 0
    return 12 if set(requested_tools).issubset(snapshot.tool_names) else -30


def _latency_fit(snapshot: ProviderSnapshot, request: RoutingRequest) -> int:
    complexity = classify_complexity(
        request.prompt, classify_task(request.prompt, request.cognitive_policy),
        request.cognitive_policy, request.reasoning_effort
    )
    return {
        "simple": {"low": 8, "standard": 4, "high": 0},
        "moderate": {"low": 7, "standard": 8, "high": 3},
        "complex": {"low": 6, "standard": 8, "high": 5},
    }[complexity][snapshot.latency_category]


def complexity_is_complex(request: RoutingRequest, task_class: TaskClass) -> bool:
    return (
        classify_complexity(
            request.prompt, task_class, request.cognitive_policy, request.reasoning_effort
        )
        == "complex"
    )


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


def approval_requirements(risk: RiskClassification) -> list[str]:
    if risk == "green":
        return []
    if risk == "yellow":
        return [
            "human review required before any external or mutating action based on this answer"
        ]
    return [
        "explicit human approval required before any consequential action based on this answer"
    ]


def _latency(complexity: Complexity) -> str:
    return {"simple": "low", "moderate": "standard", "complex": "high"}[complexity]


def _verification_strategy(task_class: TaskClass, settings: AISettings) -> str:
    if task_class == "security_review":
        return "security_review"
    if task_class == "consequential_decision":
        return "independent_review"
    if task_class == "repository_execution":
        return "repository_review"
    if task_class == "coding":
        return "tests_and_diff"
    if settings.verification_preference == "strict":
        return "source_check"
    return "response_integrity"


def _contains(text: str, *terms: str) -> bool:
    return any(term in text for term in terms)
