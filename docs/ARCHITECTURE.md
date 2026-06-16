# Architecture

## Overview

OpenCobalt is a local-first control and provenance layer for AI work. It does not replace the
agent runtimes you use -- it coordinates them, logs their results, preserves project memory,
and routes future work based on deterministic policy and verification needs.

The core is a Python package (`opencobalt`) with a Typer CLI. No persistent background daemons. The `opencobalt ui` command starts a local FastAPI server and Vite dev server on demand; both stop when the command exits. No external calls unless explicitly configured.

## Package Layout

```
src/opencobalt/
  cli.py               Typer CLI, all commands
  core/
    models.py          Pydantic schemas: SessionEvent, ToolRun, ContextPack,
                       AgentProfile, RouteDecision, VerificationResult,
                       MemoryRecord, DesignBrief
    models_discovery.py  Discovers installed Ollama models via subprocess.
                         Falls back gracefully if Ollama is absent.
    events.py          Append-only JSONL event writer
    ledger.py          SQLite source of truth (6 tables: events,
                       verification_results, route_decisions, memory_records,
                       cost_records, config)
    memory.py          MemoryStore: writes/reads MemoryRecord via ledger.
                       Markdown export is a generated mirror, not source.
    context.py         Context pack compiler. Prioritizes README + docs,
                       then src/. Caps total size. Writes to
                       .opencobalt/context/latest.md.
    router.py          Deterministic keyword-based task router. No LLM calls.
    public_safety.py   Scans repo for .env files, secret patterns, vault
                       path references, oversized files, node_modules.
    verify.py          Runs pytest and public-check. Records VerificationResult
                       to ledger.
    cost.py            CostTracker: model registry, routing modes, budget caps,
                       monthly reset.
    config.py          Config: SQLite-backed key-value store.
    benchmark.py       BenchmarkStore: records agent task results, computes
                       leaderboard and best-for-task-type lookup.
  agents/
    base_agent.py      BaseAgent ABC: run(task, dry_run) -> str;
                       compatible_skills class attribute
    registry.py        REGISTRY dict, list_agents(), get_agent()
    summarizer.py      Worker tier: blocked outside ExecutionEngine
    tagger.py          Worker tier: blocked outside ExecutionEngine
    code_reviewer.py   Manager tier: uses file-reader skill, escalation note
    context_builder.py Worker tier: real filesystem scan, no model
  skills/
    base_skill.py      BaseSkill ABC: run(**kwargs) -> SkillResult;
                       compatible_agents class attribute
    registry.py        REGISTRY dict, list_skills(agent=None), get_skill()
    file_reader.py     Read file contents, handles missing/binary files
    diff_writer.py     Generate unified diff between two strings (difflib)
    context_injector.py  Build context snippet from README + docs for a task
  integrations/
    base_integration.py   BaseIntegration ABC: install_check(), invoke(),
                          integration_status(); IntegrationProfile with tier,
                          capabilities, integration_status
    registry.py           REGISTRY dict, list_integrations(), get_integration()
    aider_integration.py       shutil.which("aider"); worker tier
    ollama_integration.py      subprocess check; worker tier
    claude_code_integration.py shutil.which("claude"); executive tier
    antigravity_integration.py shutil.which("agy"); executive agent runtime
    gemini_cli_integration.py  deprecated compatibility shim
    cursor_integration.py      GUI app stub; manager tier; status=available
    context7_integration.py    MCP server stub; manager tier; status=available
ui/
  src/App.jsx          React 18 + Tailwind 3 dashboard, 6 panels
  -- FastAPI backend on port 8000; start with opencobalt ui from project root
```

## Data Flow

```
opencobalt route TASK
  -> router.py: keyword scoring -> RouteDecision (no LLM, deterministic)
  -> ledger.py: INSERT route_decisions (with _scores in metadata)
  -> CLI: prints score table

External tool output (manual or automated handoff)
  -> cli log: SessionEvent
  -> ledger.py: INSERT events

opencobalt verify
  -> verify.py: subprocess pytest
  -> verify.py: public_safety.scan_directory
  -> ledger.py: INSERT verification_results

opencobalt agents run summarizer "some text"
  -> agents/registry.py: lookup by name
  -> agents/summarizer.py: returns ExecutionEngine boundary message
  -> Use opencobalt run "some text" --runtime ollama --dry-run for receipts

opencobalt context --summarize
  -> context.py: compile pack to .opencobalt/context/latest.md
  -> agents/summarizer.py: blocked outside ExecutionEngine

opencobalt benchmark record "task" --agent NAME --latency 300 --success
  -> benchmark.py: BenchmarkStore.record(BenchmarkRecord)
  -> .opencobalt/ledger.db benchmark_records table

opencobalt benchmark status
  -> benchmark.py: BenchmarkStore.get_leaderboard()
  -> CLI: prints ranked table with composite score
```

## Routing Tiers

| Tier | Tools | Task types |
|------|-------|------------|
| executive | Google Antigravity CLI, Claude Code | Agent-runtime workflows, architecture, security, final code, public docs, strategy |
| manager | Codex CLI, Cursor, Context7 | Tests, lint, structured cleanup, UI work, editor tasks |
| worker | Ollama (local only) | Summarization, tagging, extraction, rough drafts, local fallback |

Worker-tier models handle low-stakes, cheap, reversible tasks only. Executive-tier decisions
(architecture, security review, employer-facing content) never route to Ollama.

## Ledger Schema

```sql
events (id, timestamp, project, source, event_type, summary, raw_ref, metadata)
verification_results (id, timestamp, command, exit_code, passed, output_summary, metadata)
route_decisions (id, timestamp, task, recommended_tool, score, reasoning, tier, metadata)
memory_records (id, timestamp, project, namespace, content, source, metadata)
cost_records (id, timestamp, model_id, input_tokens, output_tokens, cost_usd, routing_mode, metadata)
config (key TEXT PRIMARY KEY, value TEXT)
```

The `benchmark_records` table lives in the same `.opencobalt/ledger.db` file but is managed
by `BenchmarkStore` in `core/benchmark.py`:

```sql
benchmark_records (id, timestamp, agent_id, task_id, task_type, latency_ms, success,
                   model_used, tier, score)
```

All tables use append-only inserts except `config`, which uses upsert by key. IDs are UUIDs.
Timestamps are UTC ISO 8601.

## Benchmark Composite Score

```
composite = (win_rate * 0.6) + (speed_score * 0.4)
speed_score = min(1000 / avg_latency_ms, 10.0)
```

A win_rate of 1.0 and avg_latency of 100ms yields: (0.6) + (min(10, 10)*0.4) = 4.6.
A win_rate of 1.0 and avg_latency of 1000ms yields: (0.6) + (1.0*0.4) = 1.0.

`get_best_for_task_type(task_type)` returns the highest-scoring agent for that task type.
The router will use this to auto-assign tasks once benchmark data accumulates.

## Integration Status Values

Each integration exposes an `integration_status()` method:

- `active`: `install_check()` returned True; the tool is on PATH and usable
- `stub`: `install_check()` returned False; the tool is not installed
- `available`: the tool is downloadable but cannot be detected via PATH (e.g. GUI apps, MCP servers)

## Runtime Paths

```
.opencobalt/
  ledger.db           SQLite ledger (source of truth; includes benchmark_records)
  context/
    latest.md         Most recent context pack (from opencobalt context)
    previous.md       Prior context pack (rotated on each context build)
  exports/
    ledger-YYYYMMDD-HHMM.md  Full ledger export (from opencobalt export)
    <project>-memory.md      Memory export (from opencobalt memory export)
```

All `.opencobalt/` paths are gitignored. They are local runtime state.

## CLI Commands

```
opencobalt route TASK               Route a task; prints score table
opencobalt log SUMMARY              Append a SessionEvent to the ledger
opencobalt log-list                 List recent logged events
opencobalt verify                   Run pytest + public-check; record result
opencobalt context                  Compile context pack to latest.md
opencobalt context-diff             Show what changed since the last context build
opencobalt memory add               Add a MemoryRecord to the ledger
opencobalt memory export            Export memory to markdown
opencobalt export                   Export full ledger to markdown
opencobalt history                  Show recent route decisions
opencobalt stats                    Summarize ledger counts by table
opencobalt benchmark                Route 10 representative tasks; show breakdown
opencobalt benchmark status         Show agent leaderboard from benchmark store
opencobalt benchmark record         Record a benchmark result manually
opencobalt agents list              List registered agents with tier and capabilities
opencobalt agents run NAME TASK     Run a named agent with a task string
opencobalt skills list              List registered skills
opencobalt skills list --agent NAME Filter skills by compatible agent
opencobalt integrations list        List integrations with tier, status, capabilities
opencobalt integrations check       Run install_check() on all integrations
opencobalt cost status              Show monthly spend and routing mode
opencobalt cost set-mode MODE       Set routing mode (cheap, standard, frontier)
opencobalt cost reset               Clear current month cost records
opencobalt config set KEY VALUE     Set a config key
opencobalt config get KEY           Get a config value
opencobalt config list              List all config keys
opencobalt session start NAME       Start a named work session
opencobalt session show             Show the active session and its decisions
opencobalt session end              End the active session
opencobalt tui                      Live 4-panel terminal dashboard
opencobalt doctor                   Full health check
opencobalt public-check             Pre-push safety scan
opencobalt lint                     Ruff lint on src/ and tests/
```

## Agents

Agents are defined in `agents/`. Each agent subclasses `BaseAgent` and declares:

- A class-level `AgentProfile` that specifies tier and capabilities
- A `compatible_skills` list of skill names the agent can use
- `run(task, dry_run=False) -> str` -- the only required method

When `dry_run=True`, the agent must return a description of what it would do without side effects.

| Name | Tier | Backend | Compatible skills |
|------|------|---------|------------------|
| summarizer | worker | blocked outside ExecutionEngine | context-injector |
| tagger | worker | blocked outside ExecutionEngine | file-reader |
| code-reviewer | manager | uses file-reader skill; escalation note | file-reader, diff-writer, context-injector |
| context-builder | worker | filesystem scan; no model | file-reader, context-injector |

## Skills

Skills are stateless utilities. Each skill subclasses `BaseSkill`, sets `name`, `description`,
and `compatible_agents`, and implements `run(**kwargs) -> SkillResult`.

Skills do not write to the ledger directly.

| Name | Description | Compatible agents |
|------|-------------|-----------------|
| file-reader | Read file contents; handles missing and binary files | code-reviewer, context-builder, tagger |
| diff-writer | Unified diff between two strings using difflib | code-reviewer |
| context-injector | Build context snippet from README + docs for a task | context-builder, summarizer, code-reviewer |

## Integrations

Integrations are defined in `integrations/`. Each integration subclasses `BaseIntegration` and
declares:

- `name`, `description`, `source_url` -- identity
- `tier` -- routing tier for this tool
- `capabilities` -- list of task capability strings
- `install_check() -> bool` -- True if the tool is on PATH
- `invoke(task) -> str` -- stub description of what the tool would do
- `integration_status()` -- returns "active", "stub", or "available"

| Name | Tier | Check method | Status |
|------|------|-------------|--------|
| aider | worker | shutil.which("aider") | stub if not installed |
| ollama | worker | subprocess ollama list | stub if not installed |
| claude-code | executive | shutil.which("claude") | stub if not installed |
| google-antigravity | executive | shutil.which("agy") | primary Google agent runtime |
| cursor | manager | not checkable via PATH | always available |
| context7 | manager | not checkable via PATH | always available |

Legacy Gemini CLI aliases resolve to `google-antigravity` with a deprecation warning. Gemini is still valid as a model-family label in model policy and cost tracking.

## Runtime Discovery

`opencobalt doctor antigravity` inspects Google Antigravity CLI without relying on undocumented flags:

1. `command -v agy` equivalent via PATH lookup
2. `agy --version`
3. `agy --help`
4. Runtime-discovered evidence for non-interactive mode, model selection, plugins, sandboxing, and related capabilities

Unknown capabilities are stored as `unknown`. OpenCobalt does not assume Antigravity browser verification, artifact paths, skills, hooks, subagents, or private storage locations until local runtime evidence exists.

## Cost Control

`CostTracker` in `core/cost.py` tracks per-run costs against a monthly cap.

Default caps: per_run=$0.10, monthly=$5.00. Routing mode defaults to "standard".

`reset_monthly_records()` deletes cost records for the current UTC calendar month.

API adapters are disabled by default: `opencobalt config set api_enabled true` must be
explicitly set before any API call is made.

## Extensibility

- New routing rules: add keywords and profiles to `router.py:_TOOL_PROFILES`
- New ledger tables: add SQL to `ledger.py:_SCHEMA` and methods to `Ledger`
- New agent: subclass `BaseAgent`, set `AgentProfile` and `compatible_skills`, implement `run()`;
  add instance to `agents/registry.py:REGISTRY`
- New skill: subclass `BaseSkill`, set `name`, `description`, and `compatible_agents`,
  implement `run()`; add to `skills/registry.py:REGISTRY`
- New integration: subclass `BaseIntegration`, set `tier` and `capabilities`, implement
  `install_check()` and `invoke()`; add to `integrations/registry.py:REGISTRY`
- New config key: `opencobalt config set key value` -- no code change needed

## What Is Not in Scope

- Multi-user access or server mode in the local version
- Vendor lock-in to any specific AI provider
- Automatic Obsidian vault writes (export path is configurable, disabled by default)
- Autonomous agent execution without human direction
