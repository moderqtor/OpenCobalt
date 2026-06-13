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
  execution_state, approval/receipt linkage.
- `mission_events`: append-only (`mev-`), enforced by SQLite triggers
  that abort UPDATE and DELETE.

## Commands

```
opencobalt missions start "goal"        create mission + run discovery (no execution)
opencobalt missions list                missions with status, approvals, receipts, outcomes
opencobalt missions show MISSION_ID     full mission state and next action
opencobalt missions advance MISSION_ID  one safe stage; stops at approval boundaries
opencobalt missions approve-step ID     approve a pending step (black stays blocked)
opencobalt missions run-step ID         dry-run; --execute to run; red needs --execute --yes
opencobalt missions outcome ID VALUE    useful / neutral / wasted / abandoned
opencobalt missions why MISSION_ID      goal, evidence, score, plan, approvals, receipts, outcome
opencobalt why MISSION_ID               the generic lineage trace also resolves mis-/mstp- ids
```

## Mission types

- `opportunity` (default): discovery runs through the Opportunity Engine.
- `evolve`: goals about improving OpenCobalt itself (deterministic keyword
  routing, no LLM) run through Evolve Mode. The evolve mission and its
  candidates back the mission; the selected candidate keeps its receipt,
  outcome, and provenance linkage. "Make OpenCobalt more useful this week"
  is a first-class mission.

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
