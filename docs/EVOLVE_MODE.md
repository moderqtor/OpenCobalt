# Evolve Mode v0

Evolve Mode is supervised self-improvement, not recursive self-replication.
OpenCobalt proposes work on itself and routes every consequential action
through its own supervision stack:

```
propose -> score -> approve -> execute -> verify -> receipt -> explain -> learn
```

Division of labor (unchanged from the rest of the system):

- The Evolve Engine proposes candidates and plans analysis. It never executes.
- The Approval Bridge authorizes steps. Yellow/red need explicit approval;
  black is blocked with no override.
- The Execution Engine runs approved steps behind the existing policy gate
  (dry-run default, `--execute`, `--execute --yes` for red).
- Receipts and `opencobalt why` make every step traceable end to end.
- Outcomes feed the same outcome history that weights future scoring.

## How candidates work

An evolve mission backs its candidates with a normal opportunity run:
every candidate is an opportunity track, every candidate plan is an
opportunity plan. That is the whole design: instead of adding another
autonomous loop, Evolve Mode reuses the opportunity, approval, execution,
receipt, provenance, and outcome systems that already exist. `opencobalt
why <CANDIDATE_ID>` therefore shows the full chain from mission and goal
down to receipts and artifacts.

Candidates come from two local sources, deterministically:

1. The roadmap. `## In Progress / Next` bullets in `docs/ROADMAP.md` become
   vertical-loop candidates; the repo already voted for them.
2. A small candidate library spanning the proposal types: tiny polish,
   vertical loop, adapter/integration, safety/provenance, demo/UX,
   research/moonshot.

## Scoring

Self-improvement scores are explainable line by line, like opportunity
scores. Dimensions: user value, implementation feasibility, testability,
demo impact, novelty, provenance value, autonomy leverage, wrapperware
escape value (largest positive weight), safety risk and time cost
(penalties).

Wrapperware escape value rewards features that connect subsystems into the
vertical loop or create proprietary local state and evidence. It penalizes
adding another runtime wrapper. This bias is intentional and tested.

## Subagent fanout (analysis only)

Each mission plans a delegation tree on the existing nested-subagent
primitives, mapping analysis roles to the tiered tools (claude-code,
codex-cli, gemini-cli):

```
evolution-strategist
  repo-cartographer
  roadmap-critic
  implementation-planner
    test-gap-finder
    demo-designer
  safety-auditor
  receipt-verifier
```

Every node carries a role, task, risk ceiling, permission scope, output
contract, parent, and depth. The tree is a plan; no node executes
externally. Real execution happens only through approved steps in the
execution engine.

## Commands

```bash
opencobalt evolve "make OpenCobalt more useful this week"
opencobalt evolve start "make OpenCobalt more useful this week"
opencobalt evolve report [MISSION_ID]
opencobalt evolve candidates [MISSION_ID] [--explain CANDIDATE_ID]
opencobalt evolve approve <CANDIDATE_ID>
opencobalt evolve run <CANDIDATE_ID> [--runtime noop] [--execute] [--yes]
opencobalt evolve roadmap [MISSION_ID] [--write]
opencobalt evolve list
opencobalt why <MISSION_ID|CANDIDATE_ID>
```

`/evolve` works inside the shell and calls the same commands.

`evolve approve` promotes the candidate's track through the Approval
Bridge and approves its approvable steps; black steps stay blocked.
`evolve run` refuses unapproved candidates and prints the approve command.
Dry-run is the default; `--execute` is required to run, `--yes` for red.

## Roadmap writes are gated

`evolve roadmap` prints structured proposals (type, title, why it matters,
repo fit, risk, tests, demo impact, escape value). Nothing touches
`docs/ROADMAP.md` unless the human passes `--write`, and even then the
engine only appends a marked candidate-ideas section; it never rewrites
existing content and writes are idempotent per mission.

## Persistence and events

Missions and candidates persist to `evolve_missions` / `evolve_candidates`
in `.opencobalt/ledger.db` (mission JSON is the source of truth; scalar
columns mirror for queries). Events stream to
`.opencobalt/events/evolve.jsonl`: mission_started, roadmap_loaded,
candidate_created, candidate_scored, delegation_created, approval_created,
execution_requested, receipt_linked, outcome_recorded, report_created.

## Safety boundaries (v0, hard)

- Works on branches; never merges to main, never pushes automatically.
  There is no auto-push path; `EvolvePolicy.allow_push` defaults to False
  and nothing reads it yet.
- No self-replication, no hidden background persistence, no daemons.
- No deploy, publish, spend, wallet, key, or credential paths.
- No network actions. The web research collector interface exists but is
  disabled by default and performs no I/O without an injected fetcher.
- Execution never bypasses the policy gate; red/black handling is the
  shared implementation, not a copy.
- v0 deliberately does not implement "edit the repo until done." The
  deliverable is the safe, inspectable loop; bounded code-editing
  execution adapters are future work behind the same gates.

## Future

Web research collectors (explicitly configured), MCP/A2A tool overlays,
and a bounded long-running mission mode are candidates for later phases.
Each must arrive behind the same approval, receipt, and provenance
requirements.
