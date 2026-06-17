# Mission State Machine v1

Missions are the durable spine that connects every supervised subsystem
OpenCobalt already has. A mission does not replace the Opportunity Engine,
the Approval Bridge, the execution layer, or Evolve Mode; it links them
into one auditable object with one lifecycle:

```
goal
  -> opportunity discovery (Opportunity Engine or Evolve Mode)
  -> evidence, scored tracks, candidates
  -> plan promotion
  -> approval-backed mission steps (Approval Bridge)
  -> policy-gated execution (Execution Engine)
  -> receipts and hashed artifacts
  -> verification
  -> provenance (why trace)
  -> outcome feedback (bounded, explainable scoring signal)
```

Nothing in the mission layer executes work directly. The Approval Bridge
remains the only approval authority and the execution policy gate remains
the only execution authority. Mission steps are durable mirrors of
approval steps that carry the linkage (mission step -> approval step ->
execution plan -> receipt) so a mission can be read end to end.
Missions remain adapter-agnostic: adapter-specific behavior belongs in the
execution adapter and normalized receipt contract, not in mission logic.

## Statuses

```
created -> evidence_gathering -> opportunities_generated
        -> candidates_generated (evolve missions only)
        -> plan_proposed -> awaiting_approval
        -> executing_approved_step -> verifying -> awaiting_feedback
        -> completed | failed | abandoned
```

`missions advance` moves at most one safe stage per call and never crosses
an approval boundary. Execution only ever happens through
`missions run-step ... --execute`.

## Durable model

All state lives in the shared `.opencobalt/ledger.db`:

- `missions`: mission_id (`mis-`), goal, mission_type, status, max_risk,
  run_id, evolve_mission_id, selected track/candidate/plan, approval
  request, last receipt, outcome.
- `mission_steps`: step_id (`mstp-`), title, risk_level, approval_state,
  execution_state, approval/receipt linkage. Auto-created missions also store
  route-step metadata in `step_json`: primitive, order, reason, whether the
  step expects `ExecutionEngine`, whether it expects a receipt, and whether it
  represents an approval expectation.
- `mission_events`: append-only (`mev-`), enforced by SQLite triggers
  that abort UPDATE and DELETE.

## Commands

```
opencobalt missions start "goal"        create mission + run discovery (no execution)
opencobalt missions list                missions with status, approvals, receipts, outcomes
opencobalt missions show MISSION_ID     full mission state and next action
opencobalt missions advance MISSION_ID  one safe stage; stops at approval boundaries
opencobalt missions promote-auto ID     promote auto route steps into pending approvals
opencobalt missions approve-step ID     approve a pending step (black stays blocked)
opencobalt missions run-step ID         dry-run; --execute to run; red needs --execute --yes
opencobalt missions outcome ID VALUE    useful / neutral / wasted / abandoned
opencobalt missions why MISSION_ID      goal, evidence, score, plan, approvals, receipts, outcome
opencobalt why MISSION_ID               the generic lineage trace also resolves mis-/mstp- ids
```

## Auto-created missions

`opencobalt auto "goal" --create-mission` creates a mission with
`mission_type=auto`. It does not run opportunity discovery, does not promote
approval requests, and does not execute anything. It persists the AutoPlan so
the natural-language front door becomes durable and resumable.

Auto mission metadata includes:

- AutoPlan id and hash
- intent
- autonomy envelope
- cognitive budget
- next recommended action
- required approval expectations
- expected receipt descriptions
- ordered route steps and their reasons

Auto route steps are mission steps without ApprovalBridge linkage. They are not
silently executable. If a future stage turns one of those route steps into
runtime work, that stage must use the existing Approval Bridge and
`ExecutionEngine`, and any receipt must be real.

`opencobalt missions promote-auto MISSION_ID` is the explicit promotion path.
It inspects the stored route steps, preserves the AutoPlan id/hash, envelope,
cognitive budget, and route-step reasons, and creates a pending ApprovalBridge
request for selected candidates. `opencobalt auto "GOAL" --create-mission
--promote` and shell `/auto GOAL --create-mission --promote` perform the same
create-then-promote sequence.

Promotion classifies route steps:

- `informational`: stays unpromoted route context.
- `approval_candidate`: becomes a pending approval request step.
- `execution_candidate`: becomes a pending approval step with an expected
  ExecutionEngine receipt description.
- `verification_candidate`: becomes a pending approval step for supervised
  verification gates.
- `blocked_authority`: becomes a black-risk placeholder that cannot be
  approved or executed in the current envelopes.

Promotion never grants approval and never runs work. It does not create
dry-run receipts yet because the current ApprovalBridge only hands steps to
`ExecutionEngine` after approval; bypassing that just to create receipts would
weaken the boundary. A later branch can add explicit dry-run receipt creation
when it can remain fully policy-gated.

`missions show`, `missions why`, and generic `why` expose the AutoPlan,
route steps, promotion classification, linked approval request/steps, any
later real receipts, unpromoted informational steps, and the next explicit
action.

## Mission types

- `opportunity` (default): discovery runs through the Opportunity Engine.
- `evolve`: goals about improving OpenCobalt itself (deterministic keyword
  routing, no LLM) run through Evolve Mode. The evolve mission and its
  candidates back the mission; the selected candidate keeps its receipt,
  outcome, and provenance linkage. "Make OpenCobalt more useful this week"
  is a first-class mission.
- `auto`: an AutoPlan persisted from `opencobalt auto --create-mission`.
  This is durable orchestration state only. It records route, envelope,
  budget, approvals, and expected receipts without hidden execution.

## Risk budget

`--max-risk green|yellow|red` only ever tightens the existing gates: a
step above the budget cannot be approved or run through the mission layer.
Black risk is blocked everywhere with no override and is not a valid
budget. The underlying policy is unchanged: dry-run is always allowed,
green/yellow execution needs `--execute`, red needs `--execute --yes`.

## Outcome feedback

Mission outcomes land in the existing opportunity outcome table, linked to
the selected track (and evolve candidate when applicable) and the latest
receipt. Outcome-weighted scoring stays bounded (capped at +/-0.1) and
explained line by line; there are no hidden self-modifying weights.

## Boundaries

- No background daemon; every command runs and exits.
- No implicit execution, auto-merge, push, deploy, publish, spend,
  messaging, credential storage, or private-key handling.
- No network I/O by default; evidence collectors stay local unless an
  explicitly configured fetcher exists (see OPPORTUNITY_ENGINE.md).
- All tests are hermetic (tmp_path SQLite isolation, noop runtime).
