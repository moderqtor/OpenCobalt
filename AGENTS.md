# AGENTS.md -- AI Tool Overlay

`OPENCOBALT.md` is the canonical OpenCobalt policy. Read it first and treat
this file as a short overlay for AI coding tools that look for AGENTS.md.

## Required Contract

- Follow `OPENCOBALT.md` for project identity, safety, execution boundaries,
  autonomy envelopes, cognitive budgets, receipts, approvals, MCP rules,
  commit/push/merge rules, and final reports.
- Manual commands remain available, but new orchestration work should move
  toward `opencobalt auto "GOAL"` and `/auto GOAL` as the natural-language
  front door.
- All real or fake runtime execution must flow through `ExecutionEngine`.
  Do not add direct subprocess paths from CLI, shell, council, pipeline,
  mission, evolve, or auto surfaces.
- Use local repo evidence before relying on memory.
- Do not assume runtime CLI syntax from installation or old notes.
- Do not push or merge unless Colin explicitly instructs it.

## Daily Operator Product Contract

- OpenCobalt is evolving into Colin's personal daily operating system for efficiency.
- Core 5 questions answered:
  1. What matters right now? (`opencobalt today` / `opencobalt next`)
  2. Why does it matter? (`opencobalt why <id>`)
  3. What is the smallest concrete next action? (`opencobalt next`)
  4. What was I doing before I was interrupted? (`opencobalt focus` / `opencobalt continue`)
  5. What happened after I acted? (`opencobalt done` / `opencobalt review`)
- Principles: Local-first, CLI-first, deterministic core, transparent prioritization formula, receipts over claims, preserve human authority, zero productivity theater.

## Guidelines for Coding Agents

1. **Schema Changes**: Place new SQLite DDL in `src/opencobalt/core/ledger.py` or dedicated store module. Use `CREATE TABLE IF NOT EXISTS`, explicit `FOREIGN KEY` constraints, append-only triggers where required, and dynamic/idempotent column migration logic.
2. **Execution Boundary**: All external process execution must route through `src/opencobalt/execution/engine.py` (`ExecutionEngine`).
3. **Quality Gates**: Before reporting completion, always run:
   ```bash
   .venv/bin/ruff check .
   .venv/bin/opencobalt public-check
   .venv/bin/pytest
   ```
4. **Receipts & Provenance**: Every task execution and commitment completion creates a receipt and attaches a provenance link in `.opencobalt/ledger.db`.

## Current Gate Baseline

On branch `daily-operator-v0` branched from HEAD `a265ef1`:
- `.venv/bin/ruff check .`: clean
- `.venv/bin/opencobalt public-check`: clean
- `.venv/bin/pytest`: 1126 passed, 1 warning

Re-run gates before making current claims.

## Context Sentinel

Final reports for Colin must begin:

```
Colin, COBALT-SENTINEL: receipts-first.
```

Then report branch, base SHA, test baseline, worktree cleanliness, push/merge
state, and local commit state. If a fact is unknown, say so.

