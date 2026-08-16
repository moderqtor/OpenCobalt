# AGENTS.md -- Coding Agent Instructions

`OPENCOBALT.md` is the canonical product and engineering doctrine. Read it
first. This file tells coding agents how to work in the repository.

## Source of truth

When sources conflict, use this precedence:

1. Current implementation and tests
2. `OPENCOBALT.md`
3. Current architecture and feature documentation
4. `README.md`
5. Historical docs, old roadmaps, previous prompts, and stale assumptions

Inspect the repository before relying on memory. Do not assume runtime CLI
syntax from installation notes. Do not preserve old product positioning merely
because it appears in many files. Do not describe planned functionality as
implemented. Do not delete useful implemented functionality merely because the
product direction changed.

## Required contract

- Follow `OPENCOBALT.md` for identity, capability routing, durable state,
  authority, provenance, execution boundaries, autonomy envelopes, cognitive
  budgets, receipts, approvals, MCP rules, and commit/push/merge rules.
- All real or fake runtime execution must flow through `ExecutionEngine`.
  Do not add direct subprocess paths from CLI, shell, council, pipeline,
  mission, evolve, or auto surfaces.
- Preserve working behavior. Avoid unnecessary rewrites and feature
  accumulation.
- Never invent provider capability. Installation is not authentication, and
  authentication is not successful invocation.
- Avoid dangerous bypass flags. Do not enable `--force`, `--yolo`,
  `--dangerously-skip-permissions`, or equivalent escape hatches.
- Protect private and generated state: `.opencobalt/`, `.env`, credentials,
  local databases, logs, and build output.
- Distinguish implemented, limited, experimental, planned, and speculative.
- Update docs when architecture or behavior changes. Do not leave
  contradictory instructions behind.

## Product surface

The primary user interaction is simple: tell OpenCobalt what you want.

In the local web workspace (`opencobalt ui`), that is Chat. On the CLI, that is
`opencobalt do "GOAL"` for autonomous intent execution and `opencobalt auto "GOAL"`
for plan-only orchestration. Behind that surface, intent interpretation,
WorkGraph generation, capability allocation, research, coding staging, approvals,
and receipts operate autonomously and remain progressively inspectable. Manual
commands are internal primitives, not the required front door.

## Working rules

1. **Inspect first.** Read the relevant modules and tests before editing.
2. **Schema changes.** Place new SQLite DDL in
   `src/opencobalt/core/ledger.py` or a dedicated store module. Use
   `CREATE TABLE IF NOT EXISTS`, explicit `FOREIGN KEY` constraints,
   append-only triggers where required, and idempotent column migration.
3. **Execution boundary.** External process execution routes through
   `src/opencobalt/execution/engine.py`.
4. **Coding authority.** Coding-agent mutations stay in a staged workspace
   until explicit promotion. Do not let a provider write the authoritative
   repository directly.
5. **Quality gates.** Before reporting completion, run:

   ```
   uv run ruff check .
   uv run opencobalt public-check
   uv run pytest
   ```

   If UI copy or frontend files changed, also run `npm run build --prefix ui`.
6. **Receipts.** Task execution and commitment completion create a receipt and
   attach provenance in `.opencobalt/ledger.db`.

## Commits and remotes

- Local commits only unless Colin explicitly says to push.
- Run `opencobalt public-check` before committing.
- Do not push or merge unless Colin explicitly instructs it.
- Preserve unrelated user changes.
- Do not commit `uv.lock` unless repository policy explicitly requires it.

## Reports

Final reports should be plain technical language: branch, base SHA, test
baseline, worktree cleanliness, push/merge state, local commits, and remaining
risk. Do not use branding slogans.

## Cursor Cloud

Use the prepared Python/uv and UI environment in this repository. Do not add
provider secrets, credentials, or `.env` files.

Normal production and API behavior does not silently enable Mock. Explicit
cloud or development smoke tests may set:

```
OPENCOBALT_ENABLE_DEVELOPMENT_MOCK=1
```

Cloud tests that use Mock are development verification, not live-provider
proof. Do not assume authenticated Antigravity, Ollama, or Cursor ACP in Cloud.

Run the normal quality gates. In headless environments start the workspace
with `opencobalt ui --no-browser`.
