# Architecture

## Overview

OpenCobalt is a local-first control plane. It does not replace the AI tools you use -- it coordinates them, logs their results, and routes future work based on what has worked before.

The core is a Python package (`opencobalt`) with a Typer CLI. No servers. No background daemons. No external calls unless explicitly configured.

## Package Layout

```
src/opencobalt/
  cli.py               Typer CLI -- entry point for all commands
  core/
    models.py          Pydantic schemas: SessionEvent, ToolRun, ContextPack,
                       AgentProfile, RouteDecision, VerificationResult,
                       MemoryRecord, DesignBrief
    models_discovery.py  Discovers installed Ollama models via subprocess.
                         Falls back gracefully if Ollama is absent.
    events.py          Append-only JSONL event writer. Adapted from Cobalt
                       Forge automation/lib/events.py.
    ledger.py          SQLite source of truth. Four tables: events,
                       verification_results, route_decisions, memory_records.
    memory.py          MemoryStore: writes/reads MemoryRecord via ledger.
                       Markdown export is a generated mirror, not source.
    context.py         Context pack compiler. Prioritizes README + docs,
                       then src/. Caps total size. Writes to
                       .opencobalt/context/latest.md.
    router.py          Deterministic keyword-based task router. No LLM
                       calls. Adapted from Cobalt Forge economic_router.py.
    public_safety.py   Scans repo for .env files, secret patterns, vault
                       path references, oversized files, node_modules.
    verify.py          Runs pytest and public-check. Records VerificationResult
                       to ledger.
```

## Data Flow

```
User task description
  -> router.py: keyword scoring -> RouteDecision
  -> ledger.py: INSERT route_decisions
  -> User acts on recommendation in external tool

External tool output (manual or automated handoff)
  -> cli log: SessionEvent
  -> ledger.py: INSERT events

opencobalt verify
  -> verify.py: subprocess pytest
  -> verify.py: public_safety.scan_directory
  -> ledger.py: INSERT verification_results
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
```

All tables use append-only inserts. IDs are UUIDs. Timestamps are UTC ISO 8601.

## Runtime Paths

```
.opencobalt/
  ledger.db           SQLite ledger (source of truth)
  context/
    latest.md         Most recent context pack
  exports/
    <project>-memory.md  Generated markdown memory export
```

All `.opencobalt/` paths are gitignored. They are local runtime state.

## Extensibility

- New routing rules: add keywords and profiles to `router.py:_TOOL_PROFILES`
- New ledger tables: add SQL to `ledger.py:_SCHEMA` and methods to `Ledger`
- Optional API adapters: add behind explicit env var checks; never call by default
- Context pack sources: extend `context.py:_prioritized_candidates` for new file types

## What Is Not in Scope

- Autonomous agent execution (OpenCobalt routes, it does not run agents)
- Multi-user access or server mode
- Vendor lock-in to any specific AI provider
- Automatic Obsidian vault writes (export path is configurable, disabled by default)
