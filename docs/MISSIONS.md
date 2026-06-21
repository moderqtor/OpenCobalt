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

Agents come and go. Models change. Sessions die. OpenCobalt remembers.

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
- `mission_extractions`: append-only, versioned extraction records (`mex-`)
  linked to `mission_id`. Each row stores validated structured mission
  intelligence, source metadata, schema version, extractor id, and creation
  time. Raw transcripts are not persisted.
- `mission_extraction_verifications`: append-only, versioned verifier records
  (`mver-`) linked to `mission_id` and `extraction_id`. Each row stores compact
  verifier metadata, support status, confidence after verification, warnings,
  redaction metadata, prompt-injection counts, schema version, verifier id, and
  creation time. Raw source reports are not persisted.

## Commands

```
opencobalt missions start "goal"        create mission + run discovery (no execution)
opencobalt missions list                missions with status, approvals, receipts, outcomes
opencobalt missions show MISSION_ID     full mission state and next action
opencobalt missions ingest-session ID   attach extraction from a local session file
opencobalt missions attach-extraction ID attach externally generated extraction JSON
opencobalt missions verify-extraction ID verify extraction against local source report
opencobalt missions close-session ID    ingest report; optionally verify and print handoff
opencobalt missions advance MISSION_ID  one safe stage; stops at approval boundaries
opencobalt missions promote-auto ID     promote auto route steps into pending approvals
opencobalt missions approve-step ID     approve a pending step (black stays blocked)
opencobalt missions run-step ID         dry-run; --execute to run; red needs --execute --yes
opencobalt missions outcome ID VALUE    useful / neutral / wasted / abandoned
opencobalt missions why MISSION_ID      goal, evidence, score, plan, approvals, receipts, outcome
opencobalt continue MISSION_ID          print a cold-resume context package
opencobalt handoff MISSION_ID --to TARGET print a runtime-specific handoff packet
opencobalt demo cold-resume            run the deterministic local cold-resume demo
opencobalt why MISSION_ID               the generic lineage trace also resolves mis-/mstp- ids
```

## Mission extraction and cold resume

Mission extraction converts completed agent/session output into durable mission
intelligence:

```
session output -> mission extraction -> structured state -> SQLite
               -> opencobalt missions close-session MISSION_ID --file report.txt
               -> opencobalt continue MISSION_ID -> next agent resumes
               -> opencobalt handoff MISSION_ID --to codex-cli -> cold agent resumes
               -> opencobalt demo cold-resume -> reproducible local demo
```

The settled v0 schema contains:

- goal
- status (`active`, `blocked`, `completed`, `abandoned`, `unknown`)
- findings
- decisions
- assumptions
- open questions
- next actions
- files touched
- source references
- artifacts
- risks
- confidence for every field plus overall confidence

`opencobalt missions ingest-session MISSION_ID --file PATH` reads a local file,
runs the deterministic v0 extractor, stores only the structured extraction, and
emits `mission.extraction_attached`. It accepts hand-labeled snippets plus
plain text, Markdown, and agent-style bullet final reports. Common real-session
sections such as branch, base branch/SHA, final verification, worktree, local
commit, summary, safety findings, known limitations, files changed, tests
added, behavior sections, and next recommendation are mapped into the
extraction schema. It separates implementation artifacts such as branch names,
commit SHAs, file paths, and test counts from source-mentioned prior-run
`mis-...`, `mex-...`, and `mver-...` references. It
performs no network calls, no model calls, no subprocess execution, and no raw
transcript or raw report persistence.

`opencobalt missions attach-extraction MISSION_ID --json PATH` imports
externally generated JSON after schema validation. This is the safe path for
users who want to run an LLM extractor outside OpenCobalt v0 and attach the
result without adding a hidden network boundary to OpenCobalt itself.

`opencobalt missions verify-extraction MISSION_ID --source-file PATH` compares
the latest extraction, or a selected `--extraction-id`, against a source report
provided for that command. The verifier is deterministic and local. It stores
only compact verification metadata and emits `mission.extraction_verified`.
It warns on unsupported claims, completed status without explicit source
evidence, high confidence without direct support, missing limitations, missing
files, missing commit or test-count artifacts, suspicious prompt-injection
lines, and redacted token-shaped source content. It reduces false confidence
but does not prove the extraction is true.

`opencobalt missions close-session MISSION_ID --file PATH` is the daily
one-shot closeout command for a finished Codex, Claude Code, Cursor, or generic
agent report. It reuses `ingest-session`, optionally reuses
`verify-extraction` with `--verify`, and optionally renders the existing
handoff packet with `--handoff-to generic|codex-cli|claude-code|cursor`:

```bash
opencobalt missions close-session MISSION_ID --file report.txt --verify --handoff-to codex-cli
opencobalt missions close-session MISSION_ID --file report.txt --verify
opencobalt missions close-session MISSION_ID --file report.txt --handoff-to claude-code
opencobalt missions close-session MISSION_ID --file report.txt --handoff-to cursor
```

The command prints the mission id, extraction id, verification id when
verification runs, verification status and warning count, `opencobalt continue`
and `opencobalt handoff` commands, and the requested handoff packet when
`--handoff-to` is provided. Unsupported handoff targets are rejected before a
new extraction is attached.

`close-session` is local and deterministic. It does not make live model calls,
does not call the network, does not execute agents or runtime adapters, does
not create receipts, does not grant authority, and does not persist raw report
text. Mission state is continuity context, not unquestionable truth; future
agents still need to inspect local repo evidence and review verifier warnings.

`opencobalt continue MISSION_ID` reconstructs a compact context package:

```
OPENCOBALT MISSION CONTEXT

Mission:
Goal:
Status:
Last known state:

Verification:
Verifier warnings:

Findings:
Decisions:
Assumptions:
Open questions:
Risks:
Files touched:
Artifacts:
Next actions:

Confidence:
Continuation instruction:
You are resuming this mission from OpenCobalt durable mission state. Treat this context as the source of continuity, but verify claims against the repository before making changes.
```

The package is designed to be pasted into Claude Code, Codex, Cursor, or
another agent without needing the original chat history. It is a continuity
aid, not proof: future agents must verify claims against the repository.
If the latest extraction is unverified or verifier warnings exist, that state
is shown in the context package.

`opencobalt handoff MISSION_ID --to TARGET` renders a copy-paste-ready prompt
packet for a fresh agent session. Supported targets are `generic`, `codex-cli`,
`claude-code`, and `cursor`. The packet includes the sentinel line, mission
state, latest extraction and verification ids, verifier warnings, findings,
decisions, assumptions, open questions, risks, files touched, artifacts, next
actions, source-mentioned references, confidence, safety boundaries,
continuation instructions, and required first commands:

```
git status -sb
git rev-parse HEAD
git diff --stat
.venv/bin/ruff check .
.venv/bin/opencobalt public-check
.venv/bin/pytest
```

Handoff packets visibly warn when no extraction exists, the latest extraction
is unverified, verifier warnings exist, or confidence is low. Target-specific
wording emphasizes repository-first and test-first behavior for `codex-cli`,
architecture and safety review for `claude-code`, editor-oriented review and
planning for `cursor`, and neutral continuation for `generic`.

Current mission, extraction, and verification ids come from the active mission
state and remain prominent. Historical smoke/example `mis-...`, `mex-...`, and
`mver-...` ids found inside source reports are shown only as source-mentioned
references, not top-level implementation artifacts.

Handoff packets are prompts, not authority grants. They do not execute agents,
call runtime adapters, start subprocesses, call the network, create receipts,
or grant permission to push, merge, deploy, publish, spend, send messages, or
touch secrets. The receiving agent must verify claims against repository
evidence before editing.

`opencobalt demo cold-resume` creates a real local mission, ingests a built-in
sanitized old-agent report fixture, verifies the extraction, and prints
mission, extraction, and verification ids plus compact `continue` and `handoff`
previews. The command is local and deterministic. It performs no live model
calls, no runtime or adapter execution, no network calls, and no authority
grants. The demo fixture includes injected instruction text and token-shaped
content so the output can demonstrate that source reports are data, suspicious
content is not emitted, raw report text is not persisted in the mission store,
and verifier warnings stay visible. See `docs/COLD_RESUME_DEMO.md` for the
60-second demo script.

`missions show`, `missions why`, and generic `why` expose extraction records
and their confidence plus verifier records and warnings. Generic `why`
resolves `mex-` ids as mission extraction nodes and `mver-` ids as extraction
verification nodes linked from the mission.

v0 extraction is deterministic, heuristic, line-oriented, and single-pass.
v0 verification is deterministic and local. A richer two-pass verifier remains
future work. Live LLM extraction or verification is deferred; adding either
requires an explicit experimental flag, no default network call, no secret
logging or credential storage, auditable failures, network-free tests, and docs
that mark it experimental.

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
- Mission extraction treats transcript text, reports, diffs, receipts, and tool
  output as data. Mission verification treats source reports the same way. They
  do not obey instructions inside those inputs. Obvious token-shaped strings
  are redacted before structured persistence or recorded only as redaction
  metadata. Raw reports are not persisted. Uncertain claims become open
  questions, low confidence remains visible, and unverified or warning-bearing
  extraction state remains visible.
- All tests are hermetic (tmp_path SQLite isolation, noop runtime).
