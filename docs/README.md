# Documentation

Canonical product and engineering docs. Historical material lives in
[history/](history/README.md) and must not be treated as current strategy.

## Start here

| File | Role |
|---|---|
| [README.md](../README.md) | Public product overview, install, first use |
| [OPENCOBALT.md](../OPENCOBALT.md) | Durable product and engineering doctrine |
| [AGENTS.md](../AGENTS.md) | Instructions for coding agents working in this repo |
| [SECURITY.md](../SECURITY.md) | Trust and authority boundaries |

Provider overlays ([CLAUDE.md](../CLAUDE.md), [GEMINI.md](../GEMINI.md)) defer
to those files.

## Architecture and direction

| File | Role |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Current system architecture |
| [ROADMAP.md](ROADMAP.md) | Near-term product sequence |
| [PERSONAL_AI_ROUTER.md](PERSONAL_AI_ROUTER.md) | Local web workspace, providers, data handling |

## Capabilities

| File | Role |
|---|---|
| [routing.md](routing.md) | Personal AI routing and capability roles |
| [research.md](research.md) | Research Missions, evidence, citations |
| [coding.md](coding.md) | Cursor ACP coding path, staging, promotion |
| [MISSIONS.md](MISSIONS.md) | Durable mission state machine |
| [MEMORY_SYSTEM.md](MEMORY_SYSTEM.md) | Memory stores |
| [SKILLS.md](SKILLS.md) | Skill policy |

## Execution and authority

| File | Role |
|---|---|
| [EXECUTION_LAYER.md](EXECUTION_LAYER.md) | Policy-gated runtime execution |
| [ARTIFACT_RECEIPTS.md](ARTIFACT_RECEIPTS.md) | Work receipts and artifact hashes |
| [APPROVAL_BRIDGE.md](APPROVAL_BRIDGE.md) | Approval lifecycle |
| [PROVENANCE.md](PROVENANCE.md) | Why-trace lineage |
| [AUTONOMY_ENVELOPES.md](AUTONOMY_ENVELOPES.md) | Autonomy vs authority envelopes |
| [ORCHESTRATION.md](ORCHESTRATION.md) | CLI AutoOrchestrator |
| [AGENT_POLICY.md](AGENT_POLICY.md) | Agent, subagent, and adapter policy |
| [ADAPTER_RECEIPT_NORMALIZATION.md](ADAPTER_RECEIPT_NORMALIZATION.md) | Adapter receipt contract |
| [PUBLIC_SAFETY.md](PUBLIC_SAFETY.md) | Public-check policy |

## Provider adapters

These describe current adapter contracts. They are not product identity.

- [ANTIGRAVITY.md](ANTIGRAVITY.md)
- [ANTIGRAVITY_CAPABILITY_DISCOVERY.md](ANTIGRAVITY_CAPABILITY_DISCOVERY.md)
- [CURSOR_RUNTIME_ADAPTER.md](CURSOR_RUNTIME_ADAPTER.md)
- [CLAUDE_CODE_RUNTIME_ADAPTER.md](CLAUDE_CODE_RUNTIME_ADAPTER.md)
- [CODEX_RUNTIME_ADAPTER.md](CODEX_RUNTIME_ADAPTER.md)
- [INTEGRATIONS.md](INTEGRATIONS.md)

## Other implemented subsystems

These exist in the CLI and ledger. They are not the primary user story.

- [MISSION_EXTRACTION.md](MISSION_EXTRACTION.md)
- [OPPORTUNITY_ENGINE.md](OPPORTUNITY_ENGINE.md)
- [EVOLVE_MODE.md](EVOLVE_MODE.md)
- [TOOL_ROUTING.md](TOOL_ROUTING.md) (legacy CLI keyword router)
