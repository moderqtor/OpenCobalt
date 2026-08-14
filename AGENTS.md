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

The ordinary user surface is Chat in the local web workspace (`opencobalt ui`).
Give OpenCobalt a goal; routing, memory, research, coding staging, approvals,
and receipts happen behind that interaction and remain inspectable.

The CLI remains a full control plane, including `opencobalt auto "GOAL"` for
plan-only orchestration. Manual commands are primitives, not the required
front door.

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

## Cursor Cloud specific instructions

Durable, non-obvious notes for working in the Cloud Agent environment. Standard
commands live in `README.md`, `pyproject.toml`, and this file's quality gates;
do not duplicate them here.

- Python deps live in a project venv at `.venv` managed by `uv`. `uv` is on
  `PATH` (added to `~/.bashrc`). Run the gates with `uv run ...` as written in
  the gates section, or `source .venv/bin/activate` first. Do not use the
  system `pip`; it is not the project environment.
- The venv is Python 3.11 (the CI target and the repo minimum). Tests,
  `ruff`, and `public-check` all pass from this venv.
- Run everything from the repository root so the CLI and UI share
  `.opencobalt/ledger.db` (the local SQLite source of truth).
- `opencobalt ui` starts FastAPI on `127.0.0.1:8000` and the Vite dev server
  on `:5173`, then blocks in the foreground; run it under `tmux` for
  background use and pass `--no-browser` in headless environments (it tries to
  open a browser otherwise).
- Vite binds IPv6 loopback: reach the UI at `http://localhost:5173`, not
  `http://127.0.0.1:5173` (IPv4 refuses). The API is reachable on either
  `127.0.0.1:8000` or `localhost:8000`.
- End-to-end Chat testing: use the built-in deterministic `mock` provider.
  Real CLI providers (Claude Code, Codex) fail closed for answer-only Chat and
  Gemini is discovery-only, so with no authenticated provider Automatic routing
  selects `mock` (it echoes `Mock response: <message>` and still produces a
  real route, WorkReceipt, and verification record).
- The `always_ask` approval policy blocks Chat execution (no approve/resume
  lifecycle exists yet); keep the default policy when testing Chat.
- If frontend files change, also run `npm run build --prefix ui` (Vite build)
  as noted in the gates.
