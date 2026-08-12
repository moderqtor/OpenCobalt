# Personal AI Router v1 Design

## Product boundary

OpenCobalt becomes Colin's local-first AI control plane without replacing its
existing mission, approval, execution, provenance, or receipt systems. The
primary surface is a local Chat workspace. Each request is classified,
constrained, ranked across discovered providers, executed through
`ExecutionEngine`, and linked to a normalized receipt. The UI exposes the
decision without requiring provider configuration before the first message.

The MVP is single-user and local. It does not add a daemon, hosted database,
telemetry, marketplace, credential store, or implicit cloud fallback. Consumer
subscriptions are never interpreted as API credentials. Executable presence,
authentication, and successful invocation remain separate provider states.

## Chosen consolidation approach

Add a focused `opencobalt.personal_ai` package that bridges existing systems.
This is preferable to expanding the current `api_server.py` and `App.jsx`
monoliths, and safer than rewriting the mature ledger and mission machinery.

- `PersonalAIStore` owns additive, foreign-keyed tables for conversations,
  messages, persona versions, provider preferences, route decisions and
  candidates, chat executions and stream events, curated memory, imported
  skill metadata, and personal-AI settings.
- `ExecutionEngine` remains the only real or simulated runtime execution
  boundary. Chat providers translate normalized requests into existing runtime
  adapters and translate engine outcomes back into chat events.
- Existing `WorkReceipt`, artifacts, verification, missions, approval policy,
  ledger events, and built-in skill registry are referenced rather than copied.
- The existing deterministic router remains available to CLI callers. The new
  router extends its rule-first philosophy with chat task classes, provider
  availability, persona affinity, privacy, local-only, cost, latency, risk,
  overrides, and outcome history.
- `api_server.py` becomes composition and compatibility routing. Typed personal
  AI endpoints live in a dedicated API router.

## Request lifecycle

1. Validate a non-empty message and resolve or create a conversation.
2. Persist the user message and requested controls.
3. Load the requested persona version and render its structured interaction
   policy separately from provider selection.
4. Classify task, privacy, autonomy, tools, skills, and verification needs.
5. Discover provider capability snapshots without performing paid work.
6. Generate and score candidates with named integer heuristic components.
7. Apply local-only and explicit override rules as hard constraints.
8. Persist the selected route and every candidate before execution.
9. Execute the selected adapter through `ExecutionEngine` and emit normalized
   NDJSON events. No fallback occurs unless the request explicitly allows it;
   any fallback is a persisted candidate transition and visible event.
10. Persist the assistant message, execution outcome, usage known from the
    adapter, receipt link, and verification status.
11. Create only explicit memory proposals, such as a message beginning with
    "remember that". Sensitive proposals require confirmation and are never
    activated silently.

Cancellation is durable request state. Simulated streaming and adapters that
support cooperative cancellation stop promptly. Blocking CLI adapters disclose
that cancellation is best-effort until their subprocess boundary supports it.

## Persona engine

Personas are versioned structured records. Historical messages and route
decisions reference the exact persona version.

Built-ins are Analytical (default), Reflective, Exploratory, Builder, Provider
Native, ChatGPT Native, Claude Native, and Gemini Native. Each version stores:

- directness, warmth, formality, verbosity, challenge, emotional attunement,
  speculation tolerance, question frequency, citation preference, and
  uncertainty explicitness as bounded five-level controls;
- allowed cognitive policies;
- provider affinity weights as routing priors;
- concise custom instructions;
- an optional named native provider family.

Provider-native profiles add only safety, route, memory, and tool context. They
never claim to reproduce hidden prompts or a provider identity. Route records
persist the requested persona, actual provider, and an explicit mismatch or
approximation disclosure.

## Provider contract

`ChatProvider` normalizes identity, discovery, health, model discovery,
capabilities, estimation, execution events, cancellation support, usage, error
categories, and engine receipts.

- Mock: deterministic local development provider. It executes through a mock
  runtime adapter in `ExecutionEngine`, then simulates streaming, tool events,
  errors, usage, and cooperative cancellation.
- Ollama: discovers installed models dynamically and executes the selected
  local model through the existing Ollama runtime adapter and engine. It is
  eligible only for bounded local tasks and never for final security,
  consequential claims, or complex repository implementation.
- Codex CLI: uses existing help-proven safe argv construction, read-only
  sandbox, approval policy `never`, timeouts, captured output, and normalized
  receipts. Authentication stays `unknown` until a bounded invocation proves
  it; executable discovery alone does not claim readiness.
- Google Antigravity: uses current runtime discovery and safe non-interactive
  support only when locally proven. Dangerous permission bypass remains off.
- Claude Code and Gemini CLI are displayed truthfully when discovered but are
  disabled or discovery-only unless their safe execution boundary and user
  enablement permit routing.

Local-only excludes every provider whose capability snapshot requires network
access. A manual override to an unavailable or disallowed provider produces an
inspectable error and never silently changes providers.

## Data safety and skills

All new tables are additive, use named-column inserts, enable foreign keys, and
have idempotent schema migration records. Conversation messages are durable
history, not curated memory. Curated memory carries scope, source attribution,
reason, lifecycle, pin state, and timestamps and supports explicit edit/delete.

Local skill import is a two-step preview/install flow. Preview resolves paths,
rejects symlinks and traversal, parses a bounded manifest, inventories files,
detects executable content and requested permissions, hashes the exact tree,
and returns a categorical trust assessment. Installation requires the preview
hash and explicit approval when risk is meaningful, copies into a bounded
`.opencobalt/skills/imported` location, pins the hash, and records a ledger
event. Imported code is never executed during inspection or installation.
Online discovery is an interface-only unavailable state in v1.

## API and UI

The API provides typed endpoints for conversations, messages, streaming chat,
cancellation, routes and reruns, personas and persona preview, providers and
bounded health checks, skills and local import, curated memory, missions,
ledger receipts, and settings/export. Existing dashboard endpoints remain for
compatibility while the new UI stops depending on misleading fields.

The UI is a restrained three-region workspace:

```text
+----------------+--------------------------------+------------------+
| conversations  | conversation                   | route inspector  |
| and primary    | messages                       | on demand        |
| navigation     |                                |                  |
|                | composer + compact controls    | request ->       |
|                |                                | route -> receipt |
+----------------+--------------------------------+------------------+
```

Primary navigation is Chat, Routes, Missions, Skills, Memory, Ledger,
Providers, and Settings. On narrow screens, the rails become drawers and Chat
remains primary.

Visual tokens use Iron `#0b0e12`, Graphite `#151a21`, Fog `#e8edf2`, Cobalt
`#5b7fff`, Receipt Amber `#d6a84b`, Provenance Green `#66b88a`, and Fault Coral
`#df7272`. Avenir Next/system sans carries interaction text and SF Mono carries
receipts and machine state. There are no gradients. The single signature
element is the provenance spine attached to each assistant response. Dark,
light, and system themes share the same information hierarchy.

## Verification and acceptance

Backend tests cover migrations, classification, scoring, overrides, local-only,
personas and mismatch disclosure, provider discovery/unavailability/fallback,
mock streaming/cancellation, Ollama and CLI adapters, conversation and route
persistence, receipt linkage, memory proposals, skill import safety, approvals,
and API contracts. The existing suite must remain green.

Frontend acceptance uses the production Vite build plus a browser smoke of the
critical vertical slice: create conversation, switch persona, send, stream,
inspect route and receipt, rerun, enforce local-only, restart, and re-open the
persisted conversation. Final gates are Ruff, public safety, full pytest,
frontend build, startup/API health, and exact database receipts.
