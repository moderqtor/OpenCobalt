# Orchestration

OpenCobalt's intended main UX is a natural-language front door:

```
opencobalt auto "GOAL"
/auto GOAL
```

Manual commands still exist. The point of orchestration is to turn them into
internal primitives so the user does not need to memorize the sequence.

## AutoOrchestrator v1

`src/opencobalt/core/auto_orchestrator.py` implements a deterministic planner.
It accepts a goal, optional autonomy envelope, optional cognitive budget, and
an execute request flag. V1 does not call an LLM and does not execute external
runtimes.

It returns an `AutoPlan` with:

- Selected intent
- Selected envelope
- Selected cognitive budget
- Ordered internal route steps
- Required approvals
- Expected receipts
- Next recommended action
- A reason for every selected primitive

## Intents

V1 classifies these intents:

- `repo_improvement`
- `runtime_adapter_work`
- `bug_fix`
- `audit_merge`
- `roadmap_design`
- `external_research`
- `mission_execution`
- `status_inspection`
- `unknown`

Classification is keyword-based and reproducible.

## Internal Primitives

The planner can select:

- Status check
- Adapter health check
- Mission start
- Opportunity discovery
- Evolve candidate generation
- Approval queue
- Receipt inspection
- Provenance why trace
- Execution dry-run through `ExecutionEngine`
- Verification gates
- Roadmap design
- External research

The `run_dry_run` primitive is always marked as `uses_execution_engine`.
No auto path may bypass the execution boundary.

## CLI and Shell Behavior

`opencobalt auto "GOAL"` prints:

- What I would do
- What I did
- Required approvals
- Expected receipts
- Next recommended action

In v1, "What I did" is planning only. No subprocess is started by the auto
front door. Shell `/auto GOAL` uses the same `AutoOrchestrator` and renderer.

## Future Direction

Future `/orch`, `/evolve`, and long-running mission loops should use the same
envelope and cognitive-budget registry. They may deepen autonomy inside a
declared envelope, but authority remains explicit.
