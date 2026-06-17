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

## Current Gate Baseline

At the start of `autonomy-envelope-and-auto-orchestrator-v1`, `main` at
`ed792859ae5896c6a2eb9a45525952c1fd130c62` verified with:

- `.venv/bin/ruff check .`: clean
- `.venv/bin/opencobalt public-check`: clean
- `.venv/bin/pytest`: 1050 passed, 1 warning

Re-run gates before making current claims.

## Context Sentinel

Final reports for Colin must begin:

```
Colin, COBALT-SENTINEL: receipts-first.
```

Then report branch, base SHA, test baseline, worktree cleanliness, push/merge
state, and local commit state. If a fact is unknown, say so.
