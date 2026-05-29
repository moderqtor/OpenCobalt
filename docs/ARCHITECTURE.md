# Architecture

## Overview

OpenCobalt is a local-first control plane. It does not replace the AI tools you use -- it coordinates them, logs their results, and routes future work based on what has worked before.

The core is a Python package (`opencobalt`) with a Typer CLI. No servers. No background daemons. No external calls unless explicitly configured.

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
    cost.py            CostTracker: model registry, routing modes, budget caps.
    config.py          Config: SQLite-backed key-value store.
  agents/
    base_agent.py      BaseAgent ABC: run(task, dry_run) -> str
    registry.py        REGISTRY dict, list_agents(), get_agent()
    summarizer.py      Worker tier: calls ollama run llama3, falls back on error
    tagger.py          Worker tier: calls ollama run llama3, falls back on error
    code_reviewer.py   Manager tier: structured stub findings, escalation note
    context_builder.py Worker tier: real filesystem scan, no model
  skills/
    base_skill.py      BaseSkill ABC: run(**kwargs) -> SkillResult
    registry.py        REGISTRY dict, list_skills(), get_skill()
    file_reader.py     Read file contents, handles missing/binary files
    diff_writer.py     Generate unified diff between two strings (difflib)
  integrations/
    base_integration.py   BaseIntegration ABC: install_check(), invoke()
    registry.py           REGISTRY dict, list_integrations(), get_integration()
    aider_integration.py  shutil.which("aider") check, invoke stub
    ollama_integration.py subprocess.run(["ollama", "list"]) check, invoke stub
ui/
  src/App.jsx          React 18 + Tailwind 3 skeleton, 6 panels
  -- backend not wired yet
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
  -> agents/summarizer.py: subprocess.run(["ollama", "run", "llama3", ...])
  -> Falls back to stub string if Ollama unavailable

opencobalt context --summarize
  -> context.py: compile pack to .opencobalt/context/latest.md
  -> agents/summarizer.py: summarize first 2000 chars via Ollama
```

## Routing Tiers

| Tier | Tools | Task types |
|------|-------|------------|
| executive | Claude Code, Gemini CLI | Architecture, security, final code, public docs, strategy |
| manager | Codex CLI, Cursor | Tests, lint, structured cleanup, UI work, editor tasks |
| worker | Ollama (local only) | Summarization, tagging, extraction, rough drafts, local fallback |

Worker-tier models handle low-stakes, cheap, reversible tasks only. Executive-tier decisions (architecture, security review, employer-facing content) never route to Ollama.

## Ledger Schema

```sql
events (id, timestamp, project, source, event_type, summary, raw_ref, metadata)
verification_results (id, timestamp, command, exit_code, passed, output_summary, metadata)
route_decisions (id, timestamp, task, recommended_tool, score, reasoning, tier, metadata)
memory_records (id, timestamp, project, namespace, content, source, metadata)
cost_records (id, timestamp, model_id, input_tokens, output_tokens, cost_usd, routing_mode, metadata)
config (key TEXT PRIMARY KEY, value TEXT)
```

All tables use append-only inserts except `config`, which uses upsert by key. IDs are UUIDs. Timestamps are UTC ISO 8601.

## Runtime Paths

```
.opencobalt/
  ledger.db           SQLite ledger (6 tables, source of truth)
  context/
    latest.md         Most recent context pack (from opencobalt context)
  exports/
    ledger-YYYYMMDD-HHMM.md  Full ledger export (from opencobalt export)
    <project>-memory.md      Memory export (from opencobalt memory export)
```

All `.opencobalt/` paths are gitignored. They are local runtime state.

## CLI Commands

```
opencobalt route TASK          Route a task description; prints score table
opencobalt log SUMMARY         Append a SessionEvent to the ledger
opencobalt log-list            List recent logged events
opencobalt verify              Run pytest + public-check; record result
opencobalt context             Compile context pack to latest.md
opencobalt memory add          Add a MemoryRecord to the ledger
opencobalt export              Export full ledger to markdown
opencobalt history             Show recent route decisions and events
opencobalt stats               Summarize ledger counts by table
opencobalt benchmark           Time a routing pass; report ms
opencobalt agents              List registered agents
opencobalt agents run NAME     Run a named agent with a task string
opencobalt skills              List registered skills
opencobalt integrations        List registered integrations and install status
opencobalt cost                Show cost summary from cost_records
opencobalt config set K V      Set a config key
opencobalt config get K        Get a config value
opencobalt config list         List all config keys and values
```

## Agents

Agents are defined in `agents/`. Each agent subclasses `BaseAgent` and declares a class-level `AgentProfile` that specifies its tier (worker, manager, executive) and a short description.

`run(task, dry_run=False) -> str` is the only required method. When `dry_run=True`, the agent must return a description of what it would do without side effects.

The four built-in agents:

| Name | Tier | Backend |
|------|------|---------|
| summarizer | worker | ollama run llama3; stub fallback |
| tagger | worker | ollama run llama3; stub fallback |
| code_reviewer | manager | structured stub; escalation note |
| context_builder | worker | filesystem scan; no model |

## Skills

Skills are defined in `skills/`. Each skill subclasses `BaseSkill`, sets a `name` and `description`, and implements `run(**kwargs) -> SkillResult`.

Skills are stateless utilities that agents and CLI commands can call. They do not write to the ledger directly.

The two built-in skills:

| Name | Description |
|------|-------------|
| file_reader | Read file contents; handles missing and binary files |
| diff_writer | Generate a unified diff between two strings using difflib |

## Integrations

Integrations are defined in `integrations/`. Each integration subclasses `BaseIntegration` and implements two methods:

- `install_check() -> bool` -- returns True if the external tool is available
- `invoke(**kwargs) -> str` -- runs the tool and returns output

The two built-in integrations:

| Name | Check method | Status |
|------|-------------|--------|
| aider | shutil.which("aider") | invoke stub |
| ollama | subprocess.run(["ollama", "list"]) | invoke stub |

## Extensibility

- New routing rules: add keywords and profiles to `router.py:_TOOL_PROFILES`
- New ledger tables: add SQL to `ledger.py:_SCHEMA` and methods to `Ledger`
- New agent: subclass `BaseAgent`, set a class-level `AgentProfile`, implement `run()`. Add instance to `agents/registry.py:REGISTRY`.
- New skill: subclass `BaseSkill`, set `name` and `description`, implement `run()`. Add to `skills/registry.py:REGISTRY`.
- New integration: subclass `BaseIntegration`, implement `install_check()` and `invoke()`. Add to `integrations/registry.py:REGISTRY`.
- New config key: `opencobalt config set key value` -- no code change needed.
- Optional API adapters: add behind explicit env var checks; never call by default
- Context pack sources: extend `context.py:_prioritized_candidates` for new file types

## What Is Not in Scope

- Multi-user access or server mode
- Vendor lock-in to any specific AI provider
- Automatic Obsidian vault writes (export path is configurable, disabled by default)
