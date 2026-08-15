# Routing

Personal AI routing lives in `src/opencobalt/personal_ai/router.py`. It plans
a route from an immutable provider snapshot. It does not execute.

A separate legacy keyword router in `src/opencobalt/core/router.py` still
powers `opencobalt route` and some CLI defaults. That tool-tier table is not
the Chat architecture. This document describes the Personal AI path.

## Flow

```
request
  -> requirements and capability role
  -> eligible provider/model candidates
  -> inspectable heuristic scoring
  -> execution through ExecutionEngine
  -> outcomes and receipts
```

Capability roles currently used:

- `cheap_local`
- `fast_general`
- `strong_reasoning`
- `research`
- `coding_analysis`
- `coding_agent`

Short low-stakes explanations (for example "Explain TCP vs UDP in three
sentences") stay on `cheap_local` or `fast_general`. Arithmetic and obvious
unit conversion can execute in-process through the `deterministic` provider.
Medical, scientific, legal, and difficult multi-step reasoning keep
`strong_reasoning`.

The router classifies **task family from the prompt**, not from cognitive
policy. An `implementation` policy may change depth or style. It does not
turn "Explain DNS caching" into a coding request. Manual provider or model
override is an execution constraint: it does not change task family,
authority, risk, or verification strategy.

The router also reads attached project path and privacy/local-only flags.
Mutating repo work becomes `coding_agent` only when a conversation
`project_path` is set. Without that path, the same text does not grant
coding-agent execution.

Manual Automatic vs Manual mode and the last provider/model preset are stored
on the conversation record (`metadata.routing`). Automatic mode does not
delete that preset. A stored unavailable provider or model is kept and shown
as stale; OpenCobalt does not substitute another model to make the control
look valid. The Chat request payload remains the execution input; conversation
routing is durable composer state, not a silent backend override of task
family or authority.

## Scoring

The recorded score is an integer sum of heuristic components, not a
probability and not a calibrated quality model. Adapter quality and cost
tiers are declared contracts (`statistically_calibrated=False`). Outcome
hooks reuse local execution history (success and latency) as
bounded integers. They are not learned quality scores.

Components that are actually populated today include:

| Component | Meaning |
|---|---|
| availability | Snapshot says the provider can run |
| capability_fit / role_fit | Requested role matches advertised roles |
| cost_fit / model_economy | Declared cost category vs request ceiling |
| persona_affinity | Persona provider affinities |
| privacy_fit | Privacy and local-only constraints |
| risk_fit | Risk vs approval policy |
| tool_fit | Requested tools/skills vs provider support |
| latency_fit | Declared latency category |
| historical_success | Recent complete vs failed executions for that provider |
| observed_latency | Bounded signal from recent execution durations, not a quality score |
| cancellation_rate | Reserved; user, disconnect, and shutdown cancellations are neutral today |
| deterministic_fit | Closed-form micro-tasks prefer the in-process deterministic provider |
| billing_fit | Local or subscription-backed near-zero marginal cost vs per-call API billing |
| provider_priority | User settings order |
| readiness_evidence | Discovery evidence, not inferred availability |
| reasoning_quality_fit | Reasoning effort vs provider strength |
| factual_sensitivity_fit / freshness_fit / citation_requirement_fit | Research-oriented heuristics |

`quota_pressure` exists on the score object and is currently unused in the
production path. Do not treat the exact numeric weights as a stable public
API.

## Constraints

- Local-only excludes any provider whose capability record requires network
  access. A manual cloud override does not weaken the rule.
- A manual provider or model choice is a routing constraint, not a safety
  bypass. If it is ineligible, the route is denied.
- There is no silent fallback. Fallback happens only when the user enables
  it, an eligible different provider exists, and the failure is in a
  supported category. Every attempt keeps its provider, status, and receipt.
- Ordinary Chat requires answer-only isolation, except coding-agent work
  which uses Cursor ACP. Codex and Claude currently fail closed for Chat.
- Cursor is ineligible for ordinary Chat and research roles.

## Personas and overrides

Personas contribute affinities and communication policy. They do not select
a vendor by themselves. If a native-family persona runs on a different
provider family, the route records an approximation and may substitute the
provider-native persona for execution policy.

See [PERSONAL_AI_ROUTER.md](PERSONAL_AI_ROUTER.md) for workspace behavior
and [ARCHITECTURE.md](ARCHITECTURE.md) for how routing sits in the system.
