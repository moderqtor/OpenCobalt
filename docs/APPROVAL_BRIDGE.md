# Approval Bridge v1

The approval bridge closes the loop between opportunity discovery and
receipt-backed execution:

```
goal -> opportunity -> evidence -> score -> plan -> approval -> execution
     -> receipt -> verification -> outcome -> future scoring
```

Division of labor:

- The Opportunity Engine proposes. It never executes anything.
- The Approval Bridge authorizes. It records explicit decisions per step.
- The Execution Engine runs. The existing policy gate stays fully in charge.
- Receipts verify. Every handoff writes a receipt with hashed artifacts.
- Outcomes teach. Receipt-evidenced outcomes feed future scoring.

This is supervised autonomy, not autonomous business execution. Nothing in
this layer spends money, publishes, touches credentials, performs network
actions, or weakens any existing safety gate.

## Concepts

| Object | Purpose |
|--------|---------|
| ApprovalRequest | One opportunity track/plan promoted into approvable steps |
| ApprovalStep | One unit of work with risk level, scope, and approval state |
| ApprovalDecision | A recorded approve/reject with reason and decider |
| ApprovalPolicy | What may be auto-approved (green read-only steps only) |
| ApprovalBridge | Promotion, decisions, and execution handoff |
| ApprovalStore | SQLite persistence in `.opencobalt/ledger.db` |

Approval states: `pending`, `approved`, `rejected`, `executed`, `failed`,
`superseded`.

Risk rules:

- Green steps may be auto-approved, and only if `ApprovalPolicy.auto_approve_green`
  allows it (default on; green is read-only by classification).
- Yellow and red steps always require an explicit `approvals approve`.
- Black steps are blocked. They cannot be approved or executed; there is no
  override flag.

## Workflow

```bash
opencobalt opportunities brainstorm "find the highest leverage way to improve OpenCobalt this week"
opencobalt opportunities report
opencobalt opportunities approve <TRACK_OR_PLAN_ID>   # promote into approval request
opencobalt approvals list
opencobalt approvals show <APPROVAL_ID>
opencobalt approvals approve <APPROVAL_ID> [--step STEP_ID] [--reason "..."]
opencobalt approvals reject <APPROVAL_ID> [--step STEP_ID] [--reason "..."]
opencobalt approvals run <APPROVAL_ID> [--step STEP_ID] [--runtime noop]   # dry-run
opencobalt approvals run <APPROVAL_ID> --execute [--yes]                   # real run
opencobalt approvals outcome <APPROVAL_ID> useful
opencobalt why <ANY_ID>
```

Promotion is idempotent: an existing non-superseded request for the same
track is reused unless `--new` is passed, which marks the old request
superseded. If the track has no plan yet, one is built at promotion time
(planning only).

## Execution rules

`approvals run` hands each approved step to the existing execution engine
(`opencobalt run` path). All existing rules apply unchanged:

- Dry-run is the default. A dry-run stores a plan and a receipt but starts
  no subprocess.
- `--execute` is required for green/yellow steps to actually run.
- `--execute --yes` is required for red steps.
- Black steps never run.
- Unapproved steps are refused, and the refusal prints the exact
  `approvals approve` command that would unblock them.
- Already executed steps are skipped unless `--rerun` is passed.

Every handoff links the resulting execution plan id and receipt id back to
the approval step, so `opencobalt why <RECEIPT_ID>` can climb from a receipt
all the way to the goal that caused it.

## Outcome feedback

`approvals outcome <APPROVAL_ID> useful|neutral|wasted|abandoned` records an
outcome for the request's opportunity track and attaches the latest executed
step's receipt as evidence. The same data is reachable through
`opencobalt opportunities outcome <TRACK_ID> useful --receipt <RECEIPT_ID>`.

Each outcome row stores track, plan, receipt, label, and notes. Together
with approval state, risk, and verification status this is the structured
training signal for outcome-weighted scoring in a later phase.

## Events

The bridge emits structured JSONL events to `.opencobalt/events/approval.jsonl`:
`approval.request_created`, `approval.request_superseded`,
`approval.step_approved`, `approval.step_rejected`,
`approval.step_executed`, `approval.step_failed`.

SQLite remains the source of truth; the JSONL spine is a mirror for UI and
tooling.
