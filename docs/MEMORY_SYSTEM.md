# Memory System

## Overview: three-layer memory architecture

OpenCobalt uses three layers of memory, each with different scope and persistence:

| Layer | Store | Path | Scope |
|-------|-------|------|-------|
| 1 -- Session memory | ObservabilitySession | `.opencobalt/observability.db` | Agent run tracking, tool call latency, per-run cost |
| 2 -- Agent memory | MemoryBridge | `.opencobalt/memories.db` | Cross-session summaries and learnings per agent |
| 3 -- Project knowledge | Khoj | localhost:42110 (Docker) | Indexed docs, architecture notes, Obsidian vault |

All three are local. No cloud services are required for layers 1 or 2. Layer 3
(Khoj) requires Docker but remains on localhost.

---

## Layer 1: Session memory (ObservabilitySession)

`opencobalt/observability.py` -- `ObservabilitySession`

Tracks each agent run as a session record. Records:
- Agent ID, task, model used
- Start and end timestamps
- Tool calls within the session: name, input/output tokens, latency
- Success or failure
- Cost in USD (when API calls are metered)

Schema:

```sql
obs_sessions (id, started_at, ended_at, agent_id, task, model, success, cost_usd)
obs_tool_calls (id, session_id, timestamp, tool_name, input_tokens, output_tokens, latency_ms)
```

The `opencobalt cost status` command shows aggregate observability stats alongside
the monthly cost budget.

---

## Layer 2: Agent memory (MemoryBridge)

`opencobalt/memory_bridge.py` -- `MemoryBridge`

Persists agent results and summaries across sessions. Supports:
- Text search across stored memories
- Per-agent filtering
- Session summary storage and retrieval

Default backend: SQLite text search at `.opencobalt/memories.db`.

If `mem0` is installed, it is imported but the SQLite path remains active because
mem0 requires an LLM and a vector store -- both are incompatible with the
local-first, no-API-calls-by-default constraint. The mem0 import guard enables
future integration without requiring it now.

Schema:

```sql
memories (id, timestamp, content, agent_id, session_id, metadata)
```

CLI commands:

```bash
opencobalt memory search "query"            search by content
opencobalt memory search "query" --agent a  filter by agent
opencobalt memory sessions                  list session summaries
opencobalt memory add "content" --agent a   write to bridge store
opencobalt memory status                    show counts and db path
```

---

## Layer 3: Project knowledge (Khoj)

Khoj is a self-hosted AI second brain that indexes documents and makes them
searchable via natural language. It runs as a Docker sidecar on localhost:42110.

Role: answer complex queries about the project that require context beyond recent
session memory. Examples: "what did we decide about the router design?", "find all
notes on SQLite migration patterns."

Khoj is NOT required for core OpenCobalt operation. All routing, ledger, and
memory commands work without it. Check its status with:

```bash
opencobalt khoj status
```

See `docs/KHOJ_INTEGRATION.md` for full setup, agent personas, and sync instructions.

---

## How context flows between layers

```
New session starts
  -> AGENTS.md + CLAUDE.md loaded into context (static policy)

Agent runs (e.g., opencobalt agents run summarizer "task")
  -> Layer 1: ObservabilitySession.start_session()
  -> Agent executes
  -> Layer 1: ObservabilitySession.end_session()
  -> Layer 2: MemoryBridge.add() stores result summary (if bridge configured)

Next session on related task
  -> Layer 2: MemoryBridge.search() retrieves relevant past decisions
  -> Layer 3: Khoj query (manual or future automated) retrieves project docs

opencobalt memory search "query"
  -> Layer 2: SQLite text search on memories.db
  -> (future) Layer 3: Khoj HTTP query if Layer 2 returns fewer than 3 results
```

---

## What gets stored where

| Data | Store | Retention |
|------|-------|-----------|
| Agent run records | observability.db | Append-only |
| Tool call logs | observability.db | Append-only |
| Agent result summaries | memories.db | Append-only |
| Session summaries | memories.db | Append-only |
| Route decisions | ledger.db | Append-only |
| Memory records (ledger) | ledger.db | Append-only |
| Session events | ledger.db | Append-only |
| Project docs, architecture notes | Khoj (Docker) | Managed by Khoj |
| Obsidian vault (selected folders) | Khoj (Docker) | Synced manually |

---

## What NOT to store

- API keys, credentials, .env file contents
- Private Obsidian vault entries unrelated to OpenCobalt
- Raw LLM completions (too large, low signal ratio)
- Personal or identifying information
- Files that would fail `opencobalt public-check`

---

## Obsidian integration plan

Sync only OpenCobalt-related Obsidian subfolders to Khoj (not the whole vault).

Recommended subfolders to sync:
- `~/your-vault/architecture/` -- design decisions and rationale
- `~/your-vault/sessions/` -- searchable session logs
- `~/your-vault/research/` -- notes on AI tools and integrations

Sync method: Khoj web UI at http://localhost:42110 or Khoj API file upload.
The sync is manual (no daemon or file watcher is required).

---

## SQLite schema summary

```
.opencobalt/ledger.db:
  events, verification_results, route_decisions, memory_records,
  cost_records, config, benchmark_records

.opencobalt/memories.db:
  memories

.opencobalt/observability.db:
  obs_sessions, obs_tool_calls
```

All `.opencobalt/` paths are gitignored. They are local runtime state.
The Markdown exports under `.opencobalt/exports/` are generated mirrors,
not the source of truth.
