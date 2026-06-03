# OpenCobalt Shell — Design Spec
_2026-06-03_

## Overview

Transform OpenCobalt from a command-per-invocation CLI into a persistent interactive shell (the "cobalt shell") that orchestrates Claude Code, Codex CLI, and Gemini CLI as subprocesses. The shell is the single interface for all AI-assisted development work: routing, memory, pipelines, background orchestration, and verification all happen from one prompt.

The implementation is additive: `opencobalt` with no arguments drops into the shell. All existing subcommands remain callable from the shell as slash commands. No existing functionality is removed or rewritten.

---

## Interaction Model

**Entry:** `opencobalt` (no args) opens the shell. Existing `opencobalt <command>` invocations continue to work unchanged.

**Input modes:**
- Plain text prompt → auto-routes, opens best tool, logs to ledger, queues background council
- `/command [args]` → runs any existing or new OpenCobalt command inline
- `/` alone → opens the command palette (filterable list of all slash commands)
- `Ctrl+C` → triggers session-end summary, then exits

**Prompt line:** `›` with inline tab-completion for slash commands. No completion on plain prompts (they go to the router).

**Status line** (rendered above the prompt on each draw):
```
● tests ok  ● council ready  ● memory 47 records  ● watching src/
```
Updated after each action. Colour-coded: green=ok, amber=pending, red=error, cobalt=active.

---

## Architecture

### New components

| File | Role |
|------|------|
| `src/opencobalt/shell.py` | REPL entry point — prompt loop, input dispatch, status line |
| `src/opencobalt/core/background.py` | Thread-based background task runner — council, test watcher |
| `src/opencobalt/core/pipeline.py` | Pipeline executor — ordered step chain with output handoff |
| `src/opencobalt/core/learning_router.py` | Adaptive routing weights from benchmark + outcome history |
| `src/opencobalt/core/knowledge.py` | Project knowledge graph — SQLite-backed dependency + decision map |

### Modified components

| File | Change |
|------|--------|
| `src/opencobalt/cli.py` | Add `opencobalt` no-args entry point → launches `shell.py` |
| `src/opencobalt/core/brief.py` | Add `generate_startup()` — compact 4-line brief for shell header |
| `src/opencobalt/core/council.py` | Expose `consult_subprocess()` — calls `claude`/`codex`/`gemini` binaries instead of REST API |
| `src/opencobalt/core/verify.py` | Add `verify_async()` — non-blocking verify for background use |
| `src/opencobalt/core/ledger.py` | Add `insert_outcome()` — records task outcome (committed/reverted/failed) for router learning |
| `pyproject.toml` | Add `prompt_toolkit>=3.0` to base deps |

### Unchanged

Everything in `agents/`, `skills/`, `integrations/`, `api_server.py`, `ui/`. The React dashboard continues to work as-is.

---

## Component Designs

### 1. Shell (`shell.py`)

Thin REPL loop built on `prompt_toolkit`. No business logic here — dispatches to existing commands and new core modules.

```
CobaltShell
  .run()                     # main loop
  .dispatch(input: str)      # route to slash command or plain router
  .render_status()           # draw status line above prompt
  .on_exit()                 # session summary + clipboard copy
```

**Slash command registry:** Shell reads all Typer commands from `cli.app` at startup and registers them as `/command` aliases. New commands (e.g. `/pipe`, `/council show`) are added as shell-only handlers before falling back to the Typer registry. No duplication.

**Plain input:** Any non-`/` input is passed to `route_task()`. The shell then:
1. Prints routing decision
2. Copies brief to clipboard
3. Logs to ledger
4. Opens winning tool via subprocess (`Popen`, detached)
5. Queues background council task

### 2. Background task runner (`background.py`)

A single `BackgroundRunner` instance lives for the shell's lifetime. Uses a `ThreadPoolExecutor` (max 3 workers — one per model). Results land in a `queue.Queue` that the main loop drains on each prompt redraw.

```
BackgroundRunner
  .submit(task_id, fn, *args)   # enqueue a background task
  .drain() -> list[Result]      # non-blocking poll for completed tasks
  .shutdown()                   # clean up on shell exit
```

**Background council:** On each plain-prompt route, `BackgroundRunner.submit()` is called with `council_subprocess(task, models=["codex","gemini"])`. When complete, a `BackgroundResult` lands in the queue and the status line updates to `▶ council ready`. Running `/council show` prints the cached result.

**Test watcher:** A `watchdog` observer (new optional dep, falls back to polling) monitors `src/` and `tests/`. On any `.py` file change, queues a `pytest -q --tb=short` run. If it fails, the status line turns red and the failure is printed inline at the next prompt.

### 3. Pipeline executor (`pipeline.py`)

Parses `/pipe "task" → step1 → step2 → ...` syntax and runs steps in sequence. Each step is either a tool invocation (subprocess) or a slash command. Output from each step is written to `.opencobalt/pipelines/<id>/step-N.txt` and injected as context into the next step's brief.

```
Pipeline
  .parse(expr: str) -> list[Step]
  .run(task: str, steps: list[Step]) -> PipelineResult
  .run_step(step, context: str) -> StepResult
```

Steps:
- `claude` / `codex` / `gemini` → opens tool with context, waits for exit, reads any output file the tool writes to `.opencobalt/pipelines/<id>/output.md`
- `/verify` → runs `run_all()` inline, blocks until complete
- `/note <text>` → writes note, continues

**Handoff protocol:** Each tool invocation writes its summary to `.opencobalt/pipelines/<id>/step-N.txt`. Convention: tool outputs a one-paragraph summary to that file when done. Pipeline injects that summary into the next step's system prompt via the brief.

Tools that don't write output files: pipeline captures their stdout if run non-interactively, or inserts a pause asking the user to summarise manually.

### 4. Learning router (`learning_router.py`)

Wraps the existing deterministic `route_task()` with an outcome-weighted adjustment layer.

```
LearningRouter
  .route(task: str) -> RouteDecision    # deterministic base + learned weights
  .record_outcome(task_id, outcome)     # committed / reverted / test_failed
  .get_weights() -> dict[str, float]    # per-tool adjustment factors
```

**Learning mechanism:** After each task, the shell prompts (or the git hook fires): did the output get committed? Did tests pass? Did you revert it? These outcomes are written to a new `outcomes` table in `ledger.db`. The learning router queries this table on startup and computes per-tool, per-task-type score adjustments (±15% max, decaying over 30 days). The base keyword scoring is never removed — learned weights are additive only.

**Ledger addition:**
```sql
CREATE TABLE IF NOT EXISTS outcomes (
  id TEXT PRIMARY KEY,
  timestamp TEXT NOT NULL,
  task_id TEXT NOT NULL,        -- references route_decisions.id
  tool TEXT NOT NULL,
  outcome TEXT NOT NULL,        -- 'committed' | 'reverted' | 'test_failed' | 'skipped'
  metadata TEXT NOT NULL DEFAULT '{}'
);
```

### 5. Knowledge graph (`knowledge.py`)

SQLite-backed graph of files, modules, decisions, and their relationships. Built incrementally from git log, static imports, and user notes.

```
KnowledgeGraph
  .ingest_git_log(n: int = 100)    # parse recent commits into change nodes
  .ingest_imports(src_dir: Path)   # static import analysis → dependency edges
  .query(question: str) -> str     # natural language query → formatted answer
  .why(file: str) -> str           # "why does X matter?" → dependency + decision trail
```

**Storage:**
```sql
CREATE TABLE IF NOT EXISTS kg_nodes (
  id TEXT PRIMARY KEY, type TEXT, label TEXT, metadata TEXT
);
CREATE TABLE IF NOT EXISTS kg_edges (
  id TEXT PRIMARY KEY, from_id TEXT, to_id TEXT, rel TEXT, metadata TEXT
);
```

Query is a keyword search + graph traversal, not an LLM call. `/graph why does auth.py matter?` runs a 2-hop traversal from `auth.py` and formats the result as a plain text trail.

---

## Automation Layer (default-on)

All six triggers are on by default. Each has a config key to disable.

| Trigger | Mechanism | Config key |
|---------|-----------|------------|
| Shell open → morning brief | `shell.py` startup | `shell.brief_on_start` |
| Git commit → log + public-check | post-commit hook (install-hooks) | `hooks.post_commit` |
| File save → background test run | watchdog in `background.py` | `shell.test_watch` |
| Shell exit → session summary | `shell.on_exit()` | `shell.summary_on_exit` |
| Every route → background council | `background.py` submit on route | `shell.background_council` |
| Usage guard | per-route check in `learning_router.py` | `shell.usage_guard` |

---

## Subprocess Orchestration (subscriptions, not API)

All model calls in the shell go through the installed binaries (`claude`, `codex`, `gemini`), not REST APIs. This uses subscription limits, not billing.

**Background council invocation:**
```python
subprocess.Popen(
    ["claude", "--print", f"Advise on: {task}"],
    stdout=output_file, stderr=subprocess.DEVNULL
)
```
`--print` flag (Claude Code) runs non-interactively and writes output to stdout. Codex and Gemini have equivalent non-interactive flags (exact flags to be confirmed against installed binary versions at implementation time — fall back to piped stdin if non-interactive mode is unavailable). Background runner captures stdout to `.opencobalt/council/<task_id>/model.txt`.

**Interactive invocation (main tool):**
```python
subprocess.Popen(["claude"])   # opens in current terminal, inherits tty
```
Shell suspends its own prompt while the tool is active. When the tool exits, shell resumes and checks for output files.

---

## Verify Loop (feature E)

After any task completes (tool process exits), `verify_async()` runs in the background:
1. `pytest -q --tb=short` — checks test suite
2. `ruff check src/ tests/` — lint
3. `gemini --print "Quick security audit of recent diff: $(git diff HEAD~1)"` — background security check

If all pass: logs `VERIFIED ✓` badge to `outcomes` table, prints green status line.
If any fail: surfaces the specific failure inline, routes it to the best fix tool automatically.

---

## `/pipe` Syntax

```
/pipe "task description" → claude → codex → /verify
/pipe "task description" → claude design → gemini review → codex implement → /verify
```

Step names map to:
- `claude` / `codex` / `gemini` → open tool interactively, wait for exit
- `claude design` / `codex implement` etc. → open tool with task-type hint in brief
- `/verify` → run inline verify
- `/note <text>` → append note, continue

Output file convention: `.opencobalt/pipelines/<id>/step-N.txt` — tool writes summary here when done. User can edit this file between steps if they want to steer the next model.

---

## Error Handling

- **Tool not on PATH:** Print install instruction, offer to skip that step in a pipeline.
- **Background task crashes:** Logged silently to `.opencobalt/background/errors.log`. Status line shows amber, not red — never interrupts the main prompt.
- **Test watcher file permission error:** Falls back to polling every 10s.
- **Pipeline step fails (non-zero exit):** Pipeline halts, prints failure, asks: retry / skip / abort.
- **Background council timeout (>60s):** Cancels the task, logs timeout to ledger, status stays blank.

---

## Testing

New test files:

| File | Coverage |
|------|----------|
| `tests/test_shell.py` | Dispatch logic, slash command registry, status line formatting |
| `tests/test_background.py` | Task queue, result draining, timeout handling |
| `tests/test_pipeline.py` | Parse syntax, step execution order, output handoff |
| `tests/test_learning_router.py` | Outcome recording, weight computation, decay |
| `tests/test_knowledge.py` | Git log ingestion, import parsing, query traversal |

All model calls mocked via `unittest.mock.patch`. No live tool invocations in tests. `prompt_toolkit` input mocked via `create_pipe_input()`.

Target: 350+ tests total (currently 287).

---

## Dependencies Added

| Package | Why | Where |
|---------|-----|-------|
| `prompt_toolkit>=3.0` | Shell REPL, completion, key bindings | `[project.dependencies]` |
| `watchdog>=4.0` | File system watcher for test-watch | `[project.optional-dependencies][shell]` |

`watchdog` is optional — background test watcher falls back to polling if absent.

---

## Migration / Backwards Compatibility

- `opencobalt <command>` continues to work exactly as before.
- All existing tests pass unchanged.
- New `outcomes` table added to `ledger.db` via `_init_schema()` — no migration needed (new table, append-only).
- `.superpowers/` added to `.gitignore`.

---

## What Is Out of Scope

- Persistent daemon / socket server
- Web-based shell UI
- Automatic code editing without human approval (pipeline steps open tools interactively)
- Semantic/embedding-based routing (learning weights stay on top of keyword scoring)
- Cross-machine sync of ledger or memory
