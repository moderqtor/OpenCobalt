"""Versioned interaction personas and deterministic policy rendering."""

from __future__ import annotations

from dataclasses import dataclass

from .models import CommunicationControls, Persona, PersonaVersion
from .store import PersonalAIStore

BUILTIN_PERSONA_IDS = (
    "analytical",
    "reflective",
    "exploratory",
    "builder",
    "provider-native",
    "chatgpt-native",
    "claude-native",
    "gemini-native",
)

_ALL_POLICIES = [
    "fast_answer",
    "deep_analysis",
    "skeptical_review",
    "creative_divergence",
    "decision_support",
    "emotional_reflection",
    "implementation",
    "research_synthesis",
    "research",
]


@dataclass(frozen=True)
class _Builtin:
    name: str
    description: str
    controls: CommunicationControls
    policies: list[str]
    affinities: dict[str, int]
    instructions: str
    native_family: str | None = None


_BUILTINS: dict[str, _Builtin] = {
    "analytical": _Builtin(
        name="Analytical",
        description="Direct, logical, evidence-sensitive, and explicit about uncertainty.",
        controls=CommunicationControls(
            directness="very_high",
            warmth="balanced",
            formality="balanced",
            verbosity="high",
            challenge_level="high",
            emotional_attunement="low",
            speculation_tolerance="low",
            question_frequency="low",
            citation_preference="very_high",
            uncertainty_explicitness="very_high",
        ),
        policies=[
            "fast_answer",
            "deep_analysis",
            "skeptical_review",
            "decision_support",
            "implementation",
            "research_synthesis",
            "research",
        ],
        affinities={"codex-cli": 8, "google-antigravity": 4, "ollama": 1},
        instructions="Challenge assumptions when evidence warrants it; distinguish facts from inference.",
    ),
    "reflective": _Builtin(
        name="Reflective",
        description="Patient, emotionally perceptive, nuanced, honest, and non-sycophantic.",
        controls=CommunicationControls(
            directness="balanced",
            warmth="very_high",
            formality="low",
            verbosity="high",
            challenge_level="balanced",
            emotional_attunement="very_high",
            speculation_tolerance="balanced",
            question_frequency="high",
            citation_preference="low",
            uncertainty_explicitness="high",
        ),
        policies=["emotional_reflection", "decision_support", "deep_analysis"],
        affinities={"claude-code": 9, "codex-cli": 2, "ollama": 1},
        instructions="Attend to ambiguity and emotion without agreeing merely to reassure.",
    ),
    "exploratory": _Builtin(
        name="Exploratory",
        description="Generative and curious while clearly separating speculation from evidence.",
        controls=CommunicationControls(
            directness="balanced",
            warmth="high",
            formality="low",
            verbosity="high",
            challenge_level="balanced",
            emotional_attunement="balanced",
            speculation_tolerance="very_high",
            question_frequency="high",
            citation_preference="balanced",
            uncertainty_explicitness="very_high",
        ),
        policies=["creative_divergence", "deep_analysis", "research_synthesis", "research"],
        affinities={"google-antigravity": 9, "codex-cli": 3, "ollama": 2},
        instructions="Generate useful connections, and label conjecture, metaphor, and evidence separately.",
    ),
    "builder": _Builtin(
        name="Builder",
        description="Action-oriented, technical, concrete, and focused on tested deliverables.",
        controls=CommunicationControls(
            directness="very_high",
            warmth="low",
            formality="balanced",
            verbosity="balanced",
            challenge_level="high",
            emotional_attunement="very_low",
            speculation_tolerance="low",
            question_frequency="very_low",
            citation_preference="balanced",
            uncertainty_explicitness="high",
        ),
        policies=["implementation", "skeptical_review", "decision_support"],
        affinities={"codex-cli": 10, "google-antigravity": 5, "ollama": 1},
        instructions="Prioritize implementation constraints, tests, verification, and concrete handoff state.",
    ),
    "provider-native": _Builtin(
        name="Provider Native",
        description="Preserves the selected provider's observable native interaction style.",
        controls=CommunicationControls(),
        policies=_ALL_POLICIES,
        affinities={},
        instructions="Add only OpenCobalt safety, routing, memory, and tool context.",
    ),
    "chatgpt-native": _Builtin(
        name="ChatGPT Native",
        description="Requests an OpenAI-native profile when an OpenAI provider is actually used.",
        controls=CommunicationControls(),
        policies=_ALL_POLICIES,
        affinities={"codex-cli": 10},
        instructions="Preserve observable provider-native behavior without claiming hidden prompt fidelity.",
        native_family="openai",
    ),
    "claude-native": _Builtin(
        name="Claude Native",
        description="Requests an Anthropic-native profile when an Anthropic provider is actually used.",
        controls=CommunicationControls(warmth="high", verbosity="high"),
        policies=_ALL_POLICIES,
        affinities={"claude-code": 10},
        instructions="Preserve observable provider-native behavior without claiming hidden prompt fidelity.",
        native_family="anthropic",
    ),
    "gemini-native": _Builtin(
        name="Gemini Native",
        description="Requests a Google-native profile when a Google provider is actually used.",
        controls=CommunicationControls(speculation_tolerance="high"),
        policies=_ALL_POLICIES,
        affinities={"google-antigravity": 10},
        instructions="Preserve observable provider-native behavior without claiming hidden prompt fidelity.",
        native_family="google",
    ),
}


def ensure_builtin_personas(store: PersonalAIStore) -> None:
    """Seed stable built-ins without changing existing persona versions."""
    for persona_id in BUILTIN_PERSONA_IDS:
        spec = _BUILTINS[persona_id]
        existing = store.get_persona(persona_id)
        if existing is not None and existing.active_version_id is not None:
            continue
        persona = existing or Persona(
            persona_id=persona_id,
            name=spec.name,
            description=spec.description,
            built_in=True,
        )
        store.save_persona(persona)
        version = PersonaVersion(
            persona_version_id=f"pver-{persona_id}-v1",
            persona_id=persona_id,
            version=1,
            controls=spec.controls,
            allowed_cognitive_policies=list(spec.policies),
            provider_affinities=dict(spec.affinities),
            custom_instructions=spec.instructions,
            native_provider_family=spec.native_family,
        )
        store.add_persona_version(version)


def duplicate_persona(
    store: PersonalAIStore,
    persona_id: str,
    name: str,
) -> Persona:
    source = store.get_persona(persona_id)
    source_version = store.get_active_persona_version(persona_id)
    if source is None or source_version is None:
        raise KeyError(f"unknown persona: {persona_id}")
    duplicate = Persona(
        name=name,
        description=f"Custom copy of {source.name}",
        built_in=False,
    )
    store.save_persona(duplicate)
    store.add_persona_version(
        PersonaVersion(
            persona_id=duplicate.persona_id,
            version=1,
            controls=source_version.controls.model_copy(deep=True),
            allowed_cognitive_policies=list(source_version.allowed_cognitive_policies),
            provider_affinities=dict(source_version.provider_affinities),
            custom_instructions=source_version.custom_instructions,
            native_provider_family=source_version.native_provider_family,
        )
    )
    result = store.get_persona(duplicate.persona_id)
    if result is None:  # pragma: no cover - database invariant
        raise RuntimeError("duplicated persona was not persisted")
    return result


def render_persona_policy(version: PersonaVersion, cognitive_policy: str) -> str:
    """Render structured controls without making a provider selection."""
    if cognitive_policy not in version.allowed_cognitive_policies:
        raise ValueError(
            f"cognitive policy {cognitive_policy!r} is not allowed by persona {version.persona_id}"
        )
    controls = version.controls
    lines = [
        f"Interaction persona: {version.persona_id}",
        f"Persona version: {version.persona_version_id}",
        f"Cognitive policy: {cognitive_policy}",
        f"Directness: {_label(controls.directness)}",
        f"Warmth: {_label(controls.warmth)}",
        f"Formality: {_label(controls.formality)}",
        f"Verbosity: {_label(controls.verbosity)}",
        f"Challenge level: {_label(controls.challenge_level)}",
        f"Emotional attunement: {_label(controls.emotional_attunement)}",
        f"Speculation tolerance: {_label(controls.speculation_tolerance)}",
        f"Question frequency: {_label(controls.question_frequency)}",
        f"Citation preference: {_label(controls.citation_preference)}",
        f"Uncertainty explicitness: {_label(controls.uncertainty_explicitness)}",
    ]
    if version.native_provider_family:
        lines.extend(
            [
                f"Requested native provider family: {version.native_provider_family}",
                "Do not claim provider identity or exact proprietary prompt replication.",
                "If another provider is used, label the result as an approximation.",
            ]
        )
    if version.custom_instructions:
        lines.append(f"Custom instructions: {version.custom_instructions}")
    return "\n".join(lines)


def _label(value: str) -> str:
    return value.replace("_", " ")
