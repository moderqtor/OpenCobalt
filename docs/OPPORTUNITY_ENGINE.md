# Opportunity Engine v0

Supervised, local-first opportunity discovery. The engine takes a broad goal,
classifies it, decomposes it into candidate tracks, gathers local evidence,
scores each track transparently, and builds policy-aware delegation plans.
It proposes; the human decides. The moat is receipts, evidence, policy, and
outcomes -- not raw autonomy.

## What v0 is and is not

v0 is supervised and local-first. It proposes opportunities and plans. It is
not autonomous business execution: it never spends money, never publishes,
never touches credentials, and never starts a subprocess on its own. Any
risky action must be approved through the existing execution policy gates
(`opencobalt run` / `opencobalt plans execute`), exactly like every other
piece of work in OpenCobalt.

Future versions may integrate web research collectors, A2A/MCP agent
exchange, browser workflows, and evaluator-driven discovery. The interfaces
for those are already in place (see Extensibility below), but v0 ships with
local collectors only and no live external calls.

## Pipeline

One call runs the whole supervised pipeline automatically:

```bash
opencobalt opportunities brainstorm "improve code quality and test coverage"
```

1. `opportunity.goal_received` -- the goal is classified deterministically
   (keyword scoring, no LLM) into one of: product, code_quality,
   security_authorized, growth, research, automation, cost_saving, design,
   strategy, unknown. Strategy catches planning-shaped goals ("highest
   leverage", "roadmap", "next step", "this week", "priority").
2. `opportunity.track_created` -- base tracks (docs improvement, test gaps,
   bug-risk scan) plus goal-class-specific tracks are generated from an
   extensible track library.
3. `opportunity.evidence_attached` -- pluggable local collectors attach
   evidence: repo scan (file counts, test ratio, TODO markers), work
   receipts, and route history. Manual notes can be attached too.
4. `opportunity.scored` -- every track gets a transparent score.
5. `opportunity.plan_created` -- the top tracks get non-executing,
   policy-aware delegation plans.
6. `opportunity.report_created` -- a ranked report with next actions.

Events land on the JSONL spine at `.opencobalt/events/opportunity.jsonl`.
Runs persist to `opportunity_runs` / `opportunity_tracks` tables in
`.opencobalt/ledger.db` so the UI can display them.

## Commands

```bash
opencobalt opportunities brainstorm "goal text"   # full pipeline, auto
opencobalt opportunities score [--explain TRACK]  # rescore + explanation
opencobalt opportunities report                   # ranked table
opencobalt opportunities plan TRACK_ID            # delegation plan (no execution)
opencobalt opportunities approve TRACK_ID         # promote into an approval request
opencobalt opportunities list                     # stored runs
opencobalt opportunities outcome TRACK_ID useful  # record what happened
```

`plan` is idempotent: it reuses the track's existing plan unless `--new` is
passed. `approve` hands the track to the approval bridge (see
`docs/APPROVAL_BRIDGE.md`), which is where execution is authorized and
`opencobalt why <id>` lineage begins to span into receipts.

## Scoring

Scores are explainable, not learned. Nine dimensions on a 0..1 scale:

| Dimension | Direction | Weight |
|-----------|-----------|--------|
| expected_impact | adds | 0.18 |
| feasibility | adds | 0.14 |
| evidence_strength | adds | 0.14 |
| verification_quality | adds | 0.10 |
| reversibility | adds | 0.10 |
| novelty | adds | 0.08 |
| monetization_potential | adds | 0.08 |
| risk | subtracts | 0.10 |
| time_cost | subtracts | 0.08 |

`evidence_strength` is computed from attached evidence; receipt-backed
evidence boosts `verification_quality`. Every contribution is one line in
the score explanation (`opportunities score --explain <track>`). Risk lowers
the total; strong evidence raises it.

## Delegation plans

Each planned track maps to a nested delegation tree built on the existing
subagent primitives (`core/delegation.py`, `core/subagent_registry.py`):

```
strategist (root, owns the track)
  researcher (gathers evidence)
    specialists per track type (test-writer, docs-editor, security-auditor,
    design-reviewer, cost-optimizer, implementer, ...)
  receipt-verifier (verifies what was produced)
```

Every node carries a role, task, risk ceiling, permission scope, output
contract, parent id, and depth. Max depth, risk ceilings, and parent-bounded
permission scopes are enforced at construction time. No subagent executes
external actions in v0: trees are plans, and execution is routed through the
existing policy gate where green/yellow steps need `--execute` and red needs
`--execute --yes`.

## Outcome tracking

`opportunities outcome <track> useful|neutral|wasted|abandoned` records what
actually happened, optionally linked to a receipt. The outcome table is the
training signal for future learned routing: which goal classes, tracks, and
plans produce useful results.

## Evaluator loop (stretch primitive)

`core/evaluator_loop.py` is a bounded propose -> evaluate -> mutate ->
keep-best primitive for evaluator-driven discovery:

- local evaluator callables only, no live external calls
- hard `max_iterations` cap (1000) and wall-clock timeout
- optional early stop at a target score
- full replayable candidate history
- when given a store, it writes a dry-run plan, a SHA-256 hashed history
  artifact, and a work receipt

It never mutates the filesystem itself; what callers do with the winning
candidate goes through the normal policy gate.

## Extensibility

- `register_track_template(goal_class, template)` adds track ideas at
  runtime without touching the engine.
- `EvidenceCollector` is a small protocol (`source_type`, `collect()`).
  A web research collector, A2A/MCP bridge, or browser workflow collector
  plugs in here later; a broken collector never blocks a run.
- `opportunity_registry()` extends the default subagent registry with
  opportunity roles; more roles can be registered the same way.
- The full run serializes losslessly to JSON (`OpportunityRun.to_dict` /
  `from_dict`) for replay and UI rendering.

## Safety posture

- No autonomous spending, publishing, deployment, or credential access.
- No subprocesses started by the engine; plans never auto-execute.
- Policy gates are reused, not weakened: risk classification comes from the
  same deterministic keywords as receipt-backed execution.
- All state stays in the repo's `.opencobalt/` directory.
- Tests are hermetic: no external calls, no live agent runtimes.
