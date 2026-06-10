# Subagents and Nested Delegation

OpenCobalt models specialist subagents and lets them delegate work to each
other as a validated plan. This is the planning foundation only: building a
delegation tree never starts a process. Execution happens later through the
receipt-backed execution layer, and results flow back as receipts and
artifacts, not prose.

## Subagent registry

`opencobalt.core.subagent_registry` holds the library. Each `SubagentSpec`
declares:

| Field | Meaning |
|-------|---------|
| `agent_id` | stable id, e.g. `impl-agent`, `receipt-verifier` |
| `specialization` | one-line role description |
| `tier` | executive / manager / worker (see AGENTS.md tier policy) |
| `tool` | runtime that serves the role (claude-code, codex-cli, gemini-cli, ollama) |
| `task_types` | task types the role resolves for |
| `capabilities` | tags used for capability discovery |
| `risk_ceiling` | riskiest work the role may accept (green / yellow / red / black) |
| `permission_scope` | widest access the role may hold (read / write / execute) |
| `output_contract` | what the role returns (report / artifact / receipt / prose) |

The default library covers implementation, tests, docs, security review,
analysis, summarization, architecture, UI critique, refactoring, integration
checks, cost analysis, receipt verification, policy audit, design review,
research scouting, benchmarks, and failure triage. `register()` adds custom
roles per registry instance; ids are unique and ceilings are validated.

## Delegation plans

`opencobalt.core.delegation.DelegationPlan` builds a tree of
`DelegationNode`s:

```python
from opencobalt.core.delegation import DelegationPlan

plan = DelegationPlan("ship the auth feature", max_depth=3)
root = plan.add_root("architect")
impl = plan.delegate(root.node_id, "impl-agent", "implement the auth store")
plan.delegate(impl.node_id, "test-gen", "write auth tests")
```

Rules enforced at construction time:

- Max depth (default 3) blocks runaway nested delegation.
- A node's risk level can never exceed its subagent's `risk_ceiling`.
- A child's permission scope can never exceed its spec's scope or its
  parent's scope. Scopes only narrow as delegation deepens.
- Unknown subagents, parents, risk levels, and scopes fail immediately with
  typed errors (`DelegationDepthError`, `RiskCeilingError`,
  `PermissionScopeError`, `UnknownSubagentError`).

Every delegation and recorded result emits a structured event (in memory via
`make_event`) so callers can persist them to the ledger or stream them to a
TUI.

## Results as receipts

Child results come back as `SubagentResult` records that reference work
receipts and artifact ids from the execution layer:

```python
plan.record_result(
    impl.node_id,
    status="succeeded",
    receipt_id=receipt.receipt_id,
    artifact_ids=receipt.artifact_ids,
)
results = plan.aggregate_results(root.node_id)
```

`to_dict()` / `from_dict()` serialize the full parent-child graph, so a plan
can be stored, inspected, or resumed.

## What this is not yet

- No autonomous execution: plans do not run themselves.
- No live agent calls: tests and planning are fully local and deterministic.
- No persistence layer of its own: callers decide where plans live.

The next step is wiring delegation nodes to `opencobalt run` so each node
executes through the policy gate and links its receipt automatically.
