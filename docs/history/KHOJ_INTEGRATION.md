# Khoj Integration

> Historical optional sidecar notes. Khoj is not part of the default
> OpenCobalt workspace.

## What Khoj is

Khoj is a self-hosted AI second brain. It indexes documents, notes, and web pages,
then makes them searchable via natural language. It runs as a Docker sidecar on
localhost:42110.

Khoj is NOT a core OpenCobalt runtime dependency. OpenCobalt works without it.
Khoj is the third layer of the OpenCobalt memory architecture: project knowledge
retrieval for complex queries that require indexed documentation.

License: Khoj is AGPL-3.0. Use as a local sidecar only. Never treat it as a
distributed dependency or link it into the main package.

## Role in OpenCobalt

```
Layer 1: ObservabilitySession  -- .opencobalt/observability.db  -- session tracking
Layer 2: MemoryBridge          -- .opencobalt/memories.db       -- agent memory
Layer 3: Khoj                  -- localhost:42110                -- project knowledge
```

Layer 3 queries go to Khoj when a task needs context that is not in recent session
memory: past architecture decisions, indexed docs, Obsidian vault notes.

## Setup

See `~/.khoj/SETUP_NOTES.md` for the full Docker setup procedure.

Quick start (after editing `.env` with your values):

```bash
cd ~/.khoj && docker-compose up -d
```

Check it is running:

```bash
opencobalt khoj status
```

## API keys

API keys are configured in `~/.khoj/.env` and never committed to the repo.
The `.env` file is at `~/.khoj/.env` (outside this repository).
Do not add API keys to any file inside the OpenCobalt repo.

To add a model key to Khoj after it is running: use the admin panel at
http://localhost:42110/server/admin under the "AI Model API" section.

## Agent personas to create

Once Khoj is running, create these agents via the web UI at http://localhost:42110:

**OpenCobalt Architect**
System prompt: You help reason about OpenCobalt architecture decisions. When asked
about design choices, reference the architecture docs and past decisions. Prefer
SQLite-backed, local-first approaches. Avoid suggesting external servers or cloud
dependencies unless the question specifically requires them.

**OpenCobalt Debugger**
System prompt: You help diagnose bugs in OpenCobalt. Search past error logs and
session notes for similar failures. Suggest targeted fixes that do not change
the public API or break existing tests.

**OpenCobalt Researcher**
System prompt: You search indexed project docs, GitHub notes, and model research
to answer questions about AI tooling, library APIs, and integration patterns.
Cite your sources from the indexed documents.

**OpenCobalt Memory Curator**
System prompt: You condense session notes, route decisions, and architecture
discussions into durable project memory entries. Remove redundant content.
Format entries for the OpenCobalt memory namespace schema.

**OpenCobalt Skeptic**
System prompt: You critique proposed changes to OpenCobalt for security risks,
overengineering, feasibility problems, and violations of the local-first
architecture constraints. Ask "what does this break?" before "what does this add?"

## Obsidian vault sync

Sync only OpenCobalt-related subfolders -- not the whole vault.

Recommended subfolders to sync:
- `~/your-vault/architecture/` -- design decisions and rationale
- `~/your-vault/sessions/` -- session logs you want searchable
- `~/your-vault/research/` -- notes on AI tools and integrations

Do not sync:
- Personal notes unrelated to OpenCobalt
- Journal or diary entries
- Files containing real credentials or tokens
- Files that would fail `opencobalt public-check`

To sync: use the Khoj web UI to add a "Computer" source pointing to each
subfolder, or use the Khoj API to upload files programmatically.

## Future: opencobalt memory search query routing to Khoj

When the Khoj integration is wired into the OpenCobalt memory layer:

1. `opencobalt memory search "query"` checks the SQLite MemoryBridge first
2. If fewer than 3 results, the query is also sent to the Khoj HTTP API
3. Results are merged and deduped by content hash before display

This is not yet implemented. The MemoryBridge and Khoj are currently independent.

## Checking Khoj status

```bash
opencobalt khoj status
```

Returns: `up version X.Y.Z` or `down -- not reachable at http://localhost:42110`.
