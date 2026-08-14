"""Deterministic, inspectable planning for personal-AI provider routes.

This module intentionally consumes immutable discovery snapshots.  Provider
discovery and execution remain separate concerns: routing produces a proposed
``RouteRecord`` plus its auditable alternatives and never invokes a runtime.
"""

from __future__ import annotations

import re
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
DomainClass = Literal[
    "general",
    "scientific",
    "medical",
    "philosophical",
    "technical",
    "legal",
    "financial",
    "personal",
]
SensitivityLevel = Literal["low", "moderate", "high"]
QualityNeed = Literal["low", "standard", "high"]
FreshnessNeed = Literal["none", "helpful", "required"]
CapabilityRole = Literal[
    "cheap_local",
    "fast_general",
    "strong_reasoning",
    "research",
    "coding_analysis",
    "coding_agent",
]
SPECIALIZED_ROLES = frozenset({"research", "coding_analysis", "coding_agent"})
CODING_AGENT_ONLY_ROLES = frozenset({"coding_analysis", "coding_agent"})


@dataclass(frozen=True)
class TaskRequirements:
    """Inspectable task demands used to score model quality against the request."""

    domain: DomainClass = "general"
    factual_sensitivity: SensitivityLevel = "low"
    reasoning_quality: QualityNeed = "standard"
    consequence: SensitivityLevel = "low"
    freshness: FreshnessNeed = "none"
    citations_required: bool = False
    latency_preference: Literal["low", "standard", "high"] = "standard"
    cost_preference: Literal["minimize", "balanced", "quality_first"] = "balanced"
    mutation_authority: Literal["none", "staged", "explicit"] = "none"
    deterministic_solvable: bool = False
    likely_tool_solvable: bool = False


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
    readiness_state: Literal["ready", "unknown", "unavailable"] = "unknown"
    authentication_state: Literal["unknown", "not_required", "verified"] = "unknown"
    unavailable_reason: str | None = None
    discovery_receipt_id: str | None = None
    execution_location: Literal["local", "remote", "unknown"] = "unknown"
    model_locality_evidence: tuple[str, ...] = ()
    display_name: str | None = None
    model_family: str | None = None
    profile_evidence: str | None = None
    capability_roles: frozenset[str] = field(default_factory=frozenset)
    discovery_source: str | None = None
    discovery_age_ms: int | None = None
    observed_latency_signal: int = 0
    cancellation_rate_signal: int = 0
    billing_classification: Literal[
        "local", "subscription_backed", "api_billed", "unknown"
    ] = "unknown"

    def __post_init__(self) -> None:
        """Reject unbounded evidence while normalizing capability collections."""
        if not -10 <= self.historical_success_signal <= 10:
            raise ValueError("historical_success_signal must be between -10 and 10")
        if not -10 <= self.observed_latency_signal <= 10:
            raise ValueError("observed_latency_signal must be between -10 and 10")
        if not -10 <= self.cancellation_rate_signal <= 10:
            raise ValueError("cancellation_rate_signal must be between -10 and 10")
        if not 0 <= self.quota_pressure <= 10:
            raise ValueError("quota_pressure must be between 0 and 10")
        if not -10 <= self.provider_priority <= 10:
            raise ValueError("provider_priority must be between -10 and 10")
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))
        object.__setattr__(self, "tool_names", frozenset(self.tool_names))
        object.__setattr__(self, "skill_names", frozenset(self.skill_names))
        object.__setattr__(self, "capability_roles", frozenset(self.capability_roles))


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
    attachment_ids: tuple[str, ...] = ()
    project_path: str | None = None


@dataclass(frozen=True)
class RoutingPlan:
    """A planned route and all considered candidates, ready for store persistence."""

    record: RouteRecord
    candidates: tuple[RouteCandidate, ...]
    task_class: TaskClass
    task_complexity: Complexity
    privacy_classification: PrivacyClassification
    risk_classification: RiskClassification
    requirements: TaskRequirements = field(default_factory=TaskRequirements)
    capability_role: CapabilityRole = "fast_general"


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
        requirements = classify_requirements(
            request.prompt, task_class, complexity, request.cognitive_policy
        )
        capability_role = classify_capability_role(
            request.prompt,
            task_class,
            complexity,
            requirements,
            project_path=request.project_path,
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
                complexity=complexity,
                requirements=requirements,
                capability_role=capability_role,
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
        actual_persona_id, mismatch = resolve_persona_for_provider(
            request.requested_persona_id,
            persona_version,
            snapshot.provider_family,
        )
        selected_tools = sorted(set(request.requested_tools) & snapshot.tool_names)
        selected_skills = _selected_skills(request, snapshot)
        if not selected_skills:
            from opencobalt.personal_ai.builtin_skills import recommend_builtin_skill

            recommended = recommend_builtin_skill(
                task_class=task_class,
                capability_role=capability_role,
                citations_required=requirements.citations_required,
                has_attachments=bool(request.attachment_ids),
                has_repository=bool(request.project_path),
            )
            if recommended is not None:
                selected_skills = [recommended.skill_id]
                reasons = list(selected.reasons)
                reasons.append(f"recommended skill contract: {recommended.skill_id}")
                selected = selected.model_copy(update={"reasons": reasons})
        reasons = list(selected.reasons)
        if request.provider_override:
            reasons.append("manual provider override honored")
        if request.model_override:
            reasons.append("manual model override honored")
        if mismatch:
            reasons.append(mismatch)
        reasons.append(
            selection_narrative(
                snapshot,
                task_class=task_class,
                complexity=complexity,
                requirements=requirements,
                capability_role=capability_role,
                local_only=local_only,
                persona_version=persona_version,
            )
        )

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
                "capability_role": capability_role,
                "risk_classification": risk,
                "local_only": local_only,
                "privacy_mode": request.privacy_mode,
                "privacy_policy": request.settings.privacy_policy,
                "cognitive_policy": request.cognitive_policy,
                "reasoning_effort": request.reasoning_effort,
                "domain": requirements.domain,
                "factual_sensitivity": requirements.factual_sensitivity,
                "reasoning_quality": requirements.reasoning_quality,
                "answer_consequence": requirements.consequence,
                "freshness_requirement": requirements.freshness,
                "citations_required": requirements.citations_required,
                "latency_preference": requirements.latency_preference,
                "cost_preference": requirements.cost_preference,
                "mutation_authority": requirements.mutation_authority,
                "deterministic_solvable": requirements.deterministic_solvable,
                "likely_tool_solvable": requirements.likely_tool_solvable,
                "provider_discovery_receipt_id": snapshot.discovery_receipt_id,
                "discovery_source": snapshot.discovery_source,
                "discovery_age_ms": snapshot.discovery_age_ms,
                "model_execution_location": snapshot.execution_location,
                "model_locality_evidence": list(snapshot.model_locality_evidence),
            },
        )
        return RoutingPlan(
            record=record,
            candidates=tuple(ranked),
            task_class=task_class,
            task_complexity=complexity,
            privacy_classification=privacy,
            risk_classification=risk,
            requirements=requirements,
            capability_role=capability_role,
        )

    def _candidate(
        self,
        *,
        route_id: str,
        request: RoutingRequest,
        snapshot: ProviderSnapshot,
        task_class: TaskClass,
        complexity: Complexity,
        requirements: TaskRequirements,
        capability_role: CapabilityRole,
        privacy: PrivacyClassification,
        risk: RiskClassification,
        local_only: bool,
        persona_version: PersonaVersion | None,
    ) -> RouteCandidate:
        demanding = _quality_sensitive(requirements)
        reasoning_points = _reasoning_quality_fit(snapshot, requirements)
        factual_points = _factual_sensitivity_fit(snapshot, requirements)
        freshness_points = _freshness_fit(snapshot, requirements)
        citation_points = _citation_requirement_fit(snapshot, requirements)
        role_points = _role_fit(snapshot, capability_role)
        components = {
            "availability": 20 if snapshot.available else -100,
            "capability_fit": _capability_fit(snapshot, task_class, capability_role),
            "role_fit": role_points,
            "cost_fit": _cost_fit(
                snapshot.cost_category,
                request.settings.cost_ceiling_category,
                demanding=demanding,
                billing_classification=snapshot.billing_classification,
            ),
            "persona_affinity": _persona_affinity(snapshot, persona_version),
            "privacy_fit": _privacy_fit(snapshot, privacy),
            "risk_fit": _risk_fit(snapshot, task_class, risk),
            "tool_fit": _tool_fit(snapshot, request.requested_tools),
            "latency_fit": _latency_fit(snapshot, complexity, demanding=demanding),
            "historical_success": snapshot.historical_success_signal,
            "observed_latency": snapshot.observed_latency_signal,
            "cancellation_rate": snapshot.cancellation_rate_signal,
            "quota_pressure": -snapshot.quota_pressure,
            "provider_priority": snapshot.provider_priority,
            "readiness_evidence": _readiness_evidence(snapshot),
            "model_economy": _model_economy(snapshot, task_class, complexity, requirements),
            "reasoning_quality_fit": reasoning_points,
            "factual_sensitivity_fit": factual_points,
            "freshness_fit": freshness_points,
            "citation_requirement_fit": citation_points,
            "deterministic_fit": (
                24
                if requirements.deterministic_solvable and snapshot.provider_id == "deterministic"
                else (-20 if snapshot.provider_id == "deterministic" else 0)
            ),
            "billing_fit": _billing_fit(snapshot, requirements, capability_role),
        }
        rejection = _rejection_reason(
            request=request,
            snapshot=snapshot,
            task_class=task_class,
            capability_role=capability_role,
            risk=risk,
            local_only=local_only,
            requirements=requirements,
        )
        reasons = [
            f"execution boundary: {'discovered' if snapshot.available else 'unavailable'}",
            (
                f"readiness evidence: {_readiness_evidence(snapshot):+d} "
                f"(health {snapshot.readiness_state}; authentication "
                f"{label_authentication(snapshot.authentication_state)})"
            ),
        ]
        quality_reason = _reasoning_quality_reason(requirements, reasoning_points)
        if quality_reason:
            reasons.append(quality_reason)
        factual_reason = _factual_sensitivity_reason(snapshot, requirements, factual_points)
        if factual_reason:
            reasons.append(factual_reason)
        for label, value in (
            ("capability fit", components["capability_fit"]),
            ("role fit", components["role_fit"]),
            ("privacy fit", components["privacy_fit"]),
            ("risk fit", components["risk_fit"]),
            ("cost fit", components["cost_fit"]),
            ("persona affinity", components["persona_affinity"]),
            ("tool fit", components["tool_fit"]),
            ("latency fit", components["latency_fit"]),
            ("historical success", components["historical_success"]),
            ("observed latency", components["observed_latency"]),
            ("cancellation rate", components["cancellation_rate"]),
            ("quota pressure", components["quota_pressure"]),
            ("provider priority", components["provider_priority"]),
            ("model economy", components["model_economy"]),
            ("freshness requirement", components["freshness_fit"]),
            ("citation requirement", components["citation_requirement_fit"]),
            ("deterministic fit", components["deterministic_fit"]),
        ):
            if value:
                reasons.append(f"{label}: {value:+d}")
        if snapshot.discovery_receipt_id:
            reasons.append(f"model discovery receipt: {snapshot.discovery_receipt_id}")
        if snapshot.model_locality_evidence:
            reasons.append(
                "model locality evidence: " + ", ".join(snapshot.model_locality_evidence)
            )
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


def _readiness_evidence(snapshot: ProviderSnapshot) -> int:
    """Prefer proven/no-auth runtimes without claiming an auth probability."""
    if not snapshot.available or snapshot.readiness_state == "unavailable":
        return 0
    if snapshot.readiness_state == "ready":
        return 4
    if snapshot.authentication_state == "verified":
        return 3
    if snapshot.authentication_state == "not_required":
        return 2
    if snapshot.requires_network:
        return -3
    return 0


def label_authentication(value: str) -> str:
    return value.replace("_", " ")


def classify_task(prompt: str, cognitive_policy: str = "fast_answer") -> TaskClass:
    """Classify semantic task family from the prompt, not from cognitive policy.

    ``cognitive_policy`` is accepted for call-site compatibility. It may change
    depth and verification rigor elsewhere. It does not redefine task family.
    """
    _ = cognitive_policy
    text = prompt.lower()
    if _contains(text, "security", "vulnerability", "credential", "secret", "api key"):
        if not _is_explanatory_request(text):
            return "security_review"
    if _is_consequential_decision_request(text):
        return "consequential_decision"
    if _contains(text, "multi-step", "multi step", "mission"):
        return "multi_step_mission"
    if _contains(text, "csv", "dataset", "spreadsheet", "data analysis"):
        return "data_analysis"
    if _contains(text, "pdf", "document", "logfile", "log file") or (
        _has_term(text, "log") and not _is_explanatory_request(text)
    ):
        return "file_analysis"
    if _has_term(text, "file") and not _is_explanatory_request(text):
        return "file_analysis"
    if _contains(
        text,
        "repository",
        "repo",
        "codebase",
        "pull request",
        "code review",
        "code-review",
        "review this code",
    ) or (_has_term(text, "git") and not _is_explanatory_request(text)):
        return "repository_execution"
    if _contains(text, "diff") and not _is_explanatory_request(text):
        return "repository_execution"
    if _contains(text, "use tool", "call tool") or (
        not _is_explanatory_request(text) and _contains(text, "run", "execute")
    ):
        return "tool_operation"
    if _is_coding_intent(text):
        return "coding"
    if _contains(
        text,
        "research",
        "literature",
        "compare evidence",
        "what evidence",
        "evidence supports",
        "evidence against",
        "evidence weakens",
        "cite sources",
        "with citations",
        "strongest evidence",
        "evidence for",
    ) or (_contains(text, "sources") and not _is_explanatory_request(text)):
        return "research"
    if _contains(text, "edit", "revise", "proofread"):
        return "editing"
    if _contains(text, "write", "rewrite", "draft", "email") and not _is_explanatory_request(text):
        return "writing"
    if _contains(text, "plan", "roadmap", "prioritize") and not _is_explanatory_request(text):
        return "planning"
    if _contains(text, "brainstorm", "creative", "story", "ideas"):
        return "creative_ideation"
    if _contains(text, "reflect", "emotion", "feel", "relationship", "i miss", "lonely", "loneliness", "grief"):
        return "personal_reflection"
    return "general_reasoning"


def _is_explanatory_request(text: str) -> bool:
    """True when the user asked for an explanation, not an action."""
    return bool(
        re.search(
            r"\b(explain|what is|what's|whats|what are|difference between|"
            r"how does|why does|how do|why do|how is|what does)\b",
            text,
        )
    )


def _is_coding_intent(text: str) -> bool:
    """True for implementation work, not incidental uses of 'code' or 'test'."""
    if _is_explanatory_request(text) and not _contains(
        text, "implement", "refactor", "write tests", "write a function", "write a parser"
    ):
        return False
    return _contains(
        text,
        "implement",
        "refactor",
        "write tests",
        "add tests",
        "unit test",
        "write a parser",
        "write a function",
        "write a method",
        "fix this bug",
        "fix the bug",
        "code this",
        "change the code",
        "source code for",
    ) or (
        _contains(text, "parser")
        and _contains(text, "write", "implement", "build", "add")
    )


def _is_consequential_decision_request(text: str) -> bool:
    if _contains(text, "hire", "firing", "should i", "prescribe", "invest in"):
        return True
    if _is_explanatory_request(text):
        return False
    return _contains(text, "medical", "legal", "financial", "investment")


def classify_complexity(
    prompt: str,
    task_class: TaskClass,
    cognitive_policy: str = "fast_answer",
    reasoning_effort: str = "medium",
) -> Complexity:
    text = prompt.lower()
    if _is_lightweight_task(prompt) or _is_bounded_explanation(prompt):
        return "simple"
    if reasoning_effort in {"high", "xhigh"}:
        return "complex"
    if task_class in {"security_review", "consequential_decision", "multi_step_mission"} or _contains(
        text, "comprehensive", "architecture", "multiple", "system-wide", "failure modes", "consensus"
    ):
        return "complex"
    if cognitive_policy in {
        "deep_analysis",
        "skeptical_review",
        "implementation",
        "research_synthesis",
        "research",
    }:
        return "moderate"
    if len(prompt.split()) <= 6 and task_class == "general_reasoning":
        return "simple"
    return "moderate"


def classify_requirements(
    prompt: str,
    task_class: TaskClass,
    complexity: Complexity,
    cognitive_policy: str = "fast_answer",
) -> TaskRequirements:
    """Score task demands independently of any provider identity."""
    text = prompt.lower()
    domain = _classify_domain(text, task_class)
    citations_required = task_class == "research" or _contains(
        text, "cite", "citation", "sources", "literature", "compare evidence"
    )
    freshness = _classify_freshness(text, task_class)
    factual = _classify_factual_sensitivity(
        text, task_class, domain, cognitive_policy, citations_required
    )
    reasoning = _classify_reasoning_quality(
        prompt, text, task_class, complexity, domain, factual, cognitive_policy
    )
    consequence = _classify_consequence(text, task_class, domain)
    lightweight = _is_lightweight_task(prompt) or _is_bounded_explanation(prompt)
    from opencobalt.personal_ai.deterministic import try_deterministic

    deterministic_solvable = try_deterministic(prompt) is not None
    if lightweight and domain == "general" and factual != "high":
        latency_preference: Literal["low", "standard", "high"] = "low"
        cost_preference: Literal["minimize", "balanced", "quality_first"] = "minimize"
    elif reasoning == "high" or factual == "high":
        latency_preference = "high"
        cost_preference = "quality_first"
    else:
        latency_preference = "standard"
        cost_preference = "balanced"
    mutation_authority: Literal["none", "staged", "explicit"] = "none"
    if _is_mutating_repository_work(text, task_class):
        mutation_authority = "staged"
    if task_class in {"security_review", "consequential_decision"}:
        mutation_authority = "explicit"
    return TaskRequirements(
        domain=domain,
        factual_sensitivity=factual,
        reasoning_quality=reasoning,
        consequence=consequence,
        freshness=freshness,
        citations_required=citations_required,
        latency_preference=latency_preference,
        cost_preference=cost_preference,
        mutation_authority=mutation_authority,
        deterministic_solvable=deterministic_solvable,
        likely_tool_solvable=task_class in {"tool_operation", "data_analysis"},
    )


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
    capability_role: CapabilityRole,
    risk: RiskClassification,
    local_only: bool,
    requirements: TaskRequirements | None = None,
) -> str | None:
    if not snapshot.available:
        return snapshot.unavailable_reason or "provider is unavailable"
    if snapshot.provider_id == "deterministic" and not (
        requirements is not None and requirements.deterministic_solvable
    ):
        return "deterministic provider is only eligible for closed-form micro-tasks"
    if local_only and (not snapshot.local or snapshot.requires_network):
        return "strict local-only policy excludes network/cloud provider"
    if request.provider_override and snapshot.provider_id != request.provider_override:
        return "excluded by manual provider override"
    if request.model_override and snapshot.model_id != request.model_override:
        return "model does not match manual override"
    if capability_role == "coding_agent" and not request.project_path:
        return "coding-agent requests require an explicit repository path"
    if (
        capability_role not in CODING_AGENT_ONLY_ROLES
        and "coding_agent" in snapshot.capability_roles
        and capability_role not in snapshot.capability_roles
        and "chat" not in snapshot.capabilities
    ):
        return f"coding-agent runtime is not eligible for {capability_role} requests"
    if capability_role == "coding_agent" and "coding_agent" not in snapshot.capability_roles:
        return "provider does not advertise required capability role: coding_agent"
    if capability_role == "coding_analysis" and not _supports_coding_analysis(snapshot):
        return "provider does not support required capability: coding_analysis"
    if capability_role not in CODING_AGENT_ONLY_ROLES:
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


def _capability_fit(
    snapshot: ProviderSnapshot, task_class: TaskClass, capability_role: CapabilityRole
) -> int:
    if capability_role in CODING_AGENT_ONLY_ROLES:
        return 20 if _supports_coding_analysis(snapshot) else -40
    return 20 if _task_capability(task_class) in snapshot.capabilities else -40


def _cost_fit(
    cost_category: str,
    ceiling: str,
    *,
    demanding: bool = False,
    billing_classification: str = "unknown",
) -> int:
    effective = cost_category
    if billing_classification == "subscription_backed" and cost_category == "standard":
        effective = "low"
    if billing_classification == "api_billed" and cost_category in {"free", "low"}:
        effective = "standard"
    if demanding:
        base = {"free": 2, "low": 2, "standard": 2, "high": -4}[effective]
    else:
        base = {"free": 8, "low": 5, "standard": 2, "high": -4}[effective]
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


def _latency_fit(
    snapshot: ProviderSnapshot, complexity: Complexity, *, demanding: bool = False
) -> int:
    if demanding:
        return {"low": 2, "standard": 4, "high": 3}[snapshot.latency_category]
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


def resolve_persona_for_provider(
    requested_persona_id: str,
    persona_version: PersonaVersion | None,
    provider_family: str,
) -> tuple[str, str | None]:
    if (
        persona_version is not None
        and persona_version.native_provider_family is not None
        and persona_version.native_provider_family != provider_family
    ):
        return (
            "provider-native",
            "requested native persona expects "
            f"{persona_version.native_provider_family}; selected provider family is "
            f"{provider_family}, so provider-native is an approximation",
        )
    return requested_persona_id, None


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


def _model_economy(
    snapshot: ProviderSnapshot,
    task_class: TaskClass,
    complexity: Complexity,
    requirements: TaskRequirements,
) -> int:
    """Prefer inexpensive models for simple work and strong models for hard work."""
    if _quality_sensitive(requirements) or task_class in {
        "research",
        "security_review",
        "consequential_decision",
    } or complexity == "complex":
        return {"strong": 4, "standard": 0, "weak": -6}[snapshot.quality_tier]
    if snapshot.billing_classification == "api_billed":
        return -10
    if snapshot.billing_classification == "subscription_backed" and snapshot.quality_tier != "weak":
        return 6
    if snapshot.cost_category == "high":
        return -10
    if snapshot.cost_category == "low" and snapshot.quality_tier != "weak":
        return 8
    if snapshot.cost_category == "free":
        return 4 if snapshot.quality_tier == "weak" else 6
    return 0


def _billing_fit(
    snapshot: ProviderSnapshot,
    requirements: TaskRequirements,
    capability_role: CapabilityRole,
) -> int:
    """Prefer local/subscription near-zero marginal cost over per-call API billing."""
    billing = snapshot.billing_classification
    if billing == "api_billed" and not _quality_sensitive(requirements):
        return -8
    if billing == "subscription_backed":
        if capability_role in {"cheap_local", "fast_general"} and snapshot.quality_tier != "weak":
            return 4
        return 2
    if billing == "local":
        return 3 if capability_role == "cheap_local" else 1
    return 0


def selection_narrative(
    snapshot: ProviderSnapshot,
    *,
    task_class: TaskClass,
    complexity: Complexity,
    requirements: TaskRequirements,
    local_only: bool,
    persona_version: PersonaVersion | None,
    capability_role: CapabilityRole = "fast_general",
) -> str:
    """Human-readable selection reason. Heuristic, not a calibrated probability."""
    label = snapshot.display_name or snapshot.model_id or snapshot.provider_id
    provider = snapshot.provider_id
    clauses: list[str] = []
    if task_class == "research":
        clauses.append("this request requires evidence-backed research and synthesis")
    elif task_class in {"security_review", "consequential_decision"}:
        clauses.append(f"this request is classified as {task_class.replace('_', ' ')}")
    elif requirements.reasoning_quality == "high":
        clauses.append(
            f"this request needs {requirements.domain} reasoning at "
            f"{requirements.reasoning_quality} quality"
        )
    elif complexity == "simple":
        clauses.append("this request is a simple completion")
    else:
        clauses.append(f"this request is {complexity} {task_class.replace('_', ' ')}")
    clauses.append(f"it is available through {provider}")
    if snapshot.model_id:
        clauses.append(
            f"its declared quality tier is {snapshot.quality_tier} with cost category "
            f"{snapshot.cost_category}"
        )
    if snapshot.profile_evidence:
        clauses.append(f"those tiers are {snapshot.profile_evidence.replace('_', ' ')}")
    if requirements.factual_sensitivity == "high":
        clauses.append("the claim is evidence-sensitive")
    if "research" in snapshot.capabilities and task_class == "research":
        clauses.append("it supports the required research capability")
    if capability_role:
        clauses.append(f"the selected capability role is {capability_role.replace('_', ' ')}")
    if local_only:
        clauses.append("the strict local-only constraint is active")
    else:
        clauses.append("no local-only constraint is active")
    if persona_version is not None:
        affinity = _persona_affinity(snapshot, persona_version)
        if affinity > 0:
            clauses.append(f"persona affinity for this runtime is {affinity}")
    return f"{label} was selected because " + "; ".join(clauses) + "."


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
    return any(_has_term(text, term) for term in terms)


def _has_term(text: str, term: str) -> bool:
    needle = term.lower()
    if " " in needle or "-" in needle:
        return needle in text
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", text) is not None


_ARITHMETIC_OPERATOR = (
    r"(?:[*x×÷/+\-]|times|plus|minus|multiplied(?:\s+by)?|divided(?:\s+by)?|"
    r"percent(?:\s+of)?|%)"
)


def _is_lightweight_task(prompt: str) -> bool:
    """True for short calculations, conversions, and extractive transforms.

    Cognitive policy is not consulted here. A default thoroughness policy must
    not turn arithmetic into strong-reasoning work.
    """
    text = prompt.strip().lower()
    if not text:
        return False
    if re.fullmatch(r"[\d\s.+\-*/x×÷()%]+", text) and re.search(r"\d", text):
        return True
    word_count = len(text.split())
    if word_count <= 16 and re.search(
        rf"\d+(?:[.,]\d+)?\s*{_ARITHMETIC_OPERATOR}\s*\d+(?:[.,]\d+)?",
        text,
    ):
        return True
    if (
        word_count <= 16
        and re.search(r"\d", text)
        and _contains(text, "convert", "calculate", "compute")
        and not _contains(
            text,
            "hypothesis",
            "evidence",
            "mechanism",
            "architecture",
            "policy",
        )
    ):
        return True
    if _contains(text, "extract", "extraction") and word_count <= 40:
        return True
    if _contains(text, "summarize", "summary") and word_count <= 25:
        return True
    return False


def _is_bounded_explanation(prompt: str) -> bool:
    """Short low-stakes explanations should not consume strong_reasoning.

    Structural: length, explanation framing, and an explicit brevity bound.
    Domain-sensitive prompts are excluded even when they are short.
    """
    text = prompt.strip().lower()
    if not text:
        return False
    word_count = len(text.split())
    if word_count > 24:
        return False
    if _contains(
        text,
        "pharmacology",
        "pathophysiology",
        "diagnosis",
        "patient",
        "dosage",
        "contraindication",
        "legal",
        "hypothesis",
        "architecture",
        "mechanism",
        "randomized",
    ):
        return False
    if not re.search(r"\b(explain|what is|what's|difference between)\b", text):
        return False
    if re.search(r"\bin\s+\d+\s+sentences?\b", text) or _contains(
        text, "briefly", "in short", "in one paragraph", "three sentences", "two sentences"
    ):
        return True
    return False


def has_explicit_format_constraint(prompt: str) -> bool:
    """True when the user named a length or format the model must obey."""
    text = prompt.strip().lower()
    if not text:
        return False
    return bool(
        re.search(r"\bin\s+\d+\s+sentences?\b", text)
        or _contains(text, "briefly", "in short", "in one paragraph", "three sentences", "two sentences")
    )


def _classify_domain(text: str, task_class: TaskClass) -> DomainClass:
    if task_class == "personal_reflection":
        return "personal"
    if task_class == "coding" or _contains(
        text, "algorithm", "compiler", "concurrency", "distributed system", "type system"
    ):
        return "technical"
    if _contains(
        text,
        "pharmacology",
        "pharmacologic",
        "receptor",
        "antagonism",
        "agonist",
        "synapse",
        "neurotransmitter",
        "pathophysiology",
        "randomized",
        "placebo",
        "mechanism",
        "hypothesis",
        "circuit-level",
        "neuron",
        "enzyme",
        "molecule",
        "clinical trial",
    ):
        return "scientific"
    if _contains(
        text,
        "diagnosis",
        "patient",
        "dosage",
        "contraindication",
        "side effect",
        "clinical",
        "therapeutic",
    ):
        return "medical"
    if _contains(
        text,
        "epistemology",
        "metaphysics",
        "phenomenology",
        "ontology",
        "thought experiment",
        "free will",
        "ethics",
        "moral",
    ):
        return "philosophical"
    if task_class == "consequential_decision" and _contains(text, "legal"):
        return "legal"
    if task_class == "consequential_decision" and _contains(text, "financial", "investment"):
        return "financial"
    return "general"


def _classify_freshness(text: str, task_class: TaskClass) -> FreshnessNeed:
    if _contains(text, "latest", "current", "today", "breaking", "as of", "this year"):
        return "required"
    if task_class == "research":
        return "helpful"
    return "none"


def _classify_factual_sensitivity(
    text: str,
    task_class: TaskClass,
    domain: DomainClass,
    cognitive_policy: str,
    citations_required: bool,
) -> SensitivityLevel:
    if _is_lightweight_task(text) or _is_bounded_explanation(text):
        return "low"
    if task_class in {"research", "consequential_decision", "security_review"} or citations_required:
        return "high"
    if domain in {"scientific", "medical", "legal", "financial"}:
        return "high"
    if cognitive_policy in {"research", "research_synthesis"} and task_class == "research":
        return "high"
    if _contains(text, "evidence", "established", "speculative", "distinguish", "cite"):
        return "high"
    if task_class in {"coding", "repository_execution", "planning"}:
        return "moderate"
    return "low"


def _classify_reasoning_quality(
    prompt: str,
    text: str,
    task_class: TaskClass,
    complexity: Complexity,
    domain: DomainClass,
    factual: SensitivityLevel,
    cognitive_policy: str,
) -> QualityNeed:
    if _is_lightweight_task(prompt) or _is_bounded_explanation(prompt):
        return "low"
    if complexity == "simple" and domain == "general" and factual != "high":
        return "low"
    if (
        complexity == "complex"
        or factual == "high"
        or domain in {"scientific", "medical", "philosophical"}
        or (
            cognitive_policy in {
                "deep_analysis",
                "skeptical_review",
                "research",
                "research_synthesis",
            }
            and complexity != "simple"
        )
        or task_class in {"research", "security_review", "consequential_decision"}
        or _contains(text, "distinguish", "hypothesis", "speculative", "nuance", "tradeoff", "tradeoffs", "failure modes")
    ):
        return "high"
    return "standard"


def _classify_consequence(text: str, task_class: TaskClass, domain: DomainClass) -> SensitivityLevel:
    if task_class in {"security_review", "consequential_decision"}:
        return "high"
    if domain == "medical" and _contains(text, "should i", "dose", "treat", "prescribe"):
        return "high"
    if domain in {"scientific", "medical", "legal", "financial"}:
        return "moderate"
    return "low"


def _quality_sensitive(requirements: TaskRequirements) -> bool:
    return (
        requirements.reasoning_quality == "high"
        or requirements.factual_sensitivity == "high"
        or requirements.citations_required
    )


def _reasoning_quality_fit(snapshot: ProviderSnapshot, requirements: TaskRequirements) -> int:
    if requirements.reasoning_quality == "high":
        return {"strong": 12, "standard": 2, "weak": -18}[snapshot.quality_tier]
    if requirements.reasoning_quality == "low":
        return {"strong": 0, "standard": 1, "weak": 2}[snapshot.quality_tier]
    return {"strong": 4, "standard": 4, "weak": -2}[snapshot.quality_tier]


def _factual_sensitivity_fit(snapshot: ProviderSnapshot, requirements: TaskRequirements) -> int:
    if requirements.factual_sensitivity == "high":
        return {"strong": 10, "standard": 1, "weak": -15}[snapshot.quality_tier]
    if requirements.factual_sensitivity == "moderate":
        return {"strong": 4, "standard": 2, "weak": -4}[snapshot.quality_tier]
    return 0


def _freshness_fit(snapshot: ProviderSnapshot, requirements: TaskRequirements) -> int:
    if requirements.freshness != "required":
        return 0
    if snapshot.local and not snapshot.requires_network:
        return -6
    return 4


def _citation_requirement_fit(snapshot: ProviderSnapshot, requirements: TaskRequirements) -> int:
    if not requirements.citations_required:
        return 0
    if "research" not in snapshot.capabilities:
        return -8
    return {"strong": 6, "standard": 2, "weak": -4}[snapshot.quality_tier]


def _reasoning_quality_reason(requirements: TaskRequirements, points: int) -> str | None:
    if not points:
        return None
    if requirements.reasoning_quality == "high":
        domain = requirements.domain if requirements.domain != "general" else "demanding"
        return f"{domain} reasoning quality requirement: {points:+d}"
    return f"reasoning quality fit: {points:+d}"


def _factual_sensitivity_reason(
    snapshot: ProviderSnapshot, requirements: TaskRequirements, points: int
) -> str | None:
    if not points:
        return None
    if requirements.factual_sensitivity == "high" and snapshot.quality_tier == "weak":
        return f"weak model quality penalty for evidence-sensitive synthesis: {points:+d}"
    if requirements.factual_sensitivity == "high":
        return f"evidence-sensitive synthesis quality: {points:+d}"
    return f"factual sensitivity fit: {points:+d}"


def classify_capability_role(
    prompt: str,
    task_class: TaskClass,
    complexity: Complexity,
    requirements: TaskRequirements,
    *,
    project_path: str | None = None,
) -> CapabilityRole:
    """Map task requirements onto a provider-neutral capability role."""
    text = prompt.lower()
    attached_repo = bool(project_path and project_path.strip())
    if task_class == "research" or requirements.citations_required:
        return "research"
    if attached_repo and _is_mutating_repository_work(text, task_class):
        return "coding_agent"
    if attached_repo and _is_repository_analysis(text, task_class):
        return "coding_analysis"
    if _is_lightweight_task(prompt) or (
        complexity == "simple" and requirements.reasoning_quality == "low"
    ):
        return "cheap_local"
    if _is_bounded_explanation(prompt) and requirements.domain == "general":
        return "fast_general"
    if (
        requirements.reasoning_quality == "high"
        or requirements.domain in {"scientific", "medical", "philosophical", "legal"}
        or task_class in {"security_review", "consequential_decision"}
    ):
        return "strong_reasoning"
    return "fast_general"


def _supports_coding_analysis(snapshot: ProviderSnapshot) -> bool:
    return bool(
        "coding_analysis" in snapshot.capability_roles
        or "coding_agent" in snapshot.capability_roles
        or "coding" in snapshot.capabilities
        or "file_analysis" in snapshot.capabilities
        or "chat" in snapshot.capabilities
    )


def _role_fit(snapshot: ProviderSnapshot, capability_role: CapabilityRole) -> int:
    advertised = snapshot.capability_roles
    if capability_role in advertised:
        return {
            "coding_agent": 36,
            "coding_analysis": 24,
            "research": 16,
            "strong_reasoning": 10,
            "cheap_local": 10,
            "fast_general": 8,
        }[capability_role]
    if capability_role == "coding_agent":
        return -40
    if capability_role == "coding_analysis" and (
        "coding" in snapshot.capabilities or "file_analysis" in snapshot.capabilities
    ):
        return 4
    if capability_role == "cheap_local" and snapshot.cost_category == "free":
        return 8
    return 0


def _is_mutating_repository_work(text: str, task_class: TaskClass) -> bool:
    if _contains(
        text,
        "refactor",
        "implement",
        "apply the change",
        "write tests",
        "run tests",
        "run the tests",
        "fix the bug",
        "patch",
        "commit",
        "create a file",
        "modify",
        "edit the",
        "change the code",
        "update this repository",
        "update the repository",
    ):
        return True
    return task_class in {"repository_execution", "coding"} and _contains(
        text, "run", "execute", "write", "fix", "implement", "refactor"
    )


def _is_repository_analysis(text: str, task_class: TaskClass) -> bool:
    if _is_mutating_repository_work(text, task_class):
        return False
    if task_class in {"coding", "repository_execution", "file_analysis"}:
        return True
    if _looks_like_source_path(text):
        return True
    return _contains(text, "codebase", "source code", "this file", "this module")


_SOURCE_PATH = re.compile(
    r"(?:^|[\s`])(?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]{1,8}|(?:^|[\s`])[\w.-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|rb|c|cc|cpp|h|md)"
)


def _looks_like_source_path(text: str) -> bool:
    return _SOURCE_PATH.search(text) is not None
