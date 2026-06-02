# AGENTS.md -- OpenCobalt canonical policy

This file is the canonical policy for all AI coding tools working on OpenCobalt.
Claude Code reads CLAUDE.md (which references this file). Codex, Copilot, Cursor,
and Gemini CLI read this file directly.

---

## Project identity

OpenCobalt is a local-first AI orchestration control plane. It routes tasks to the
right AI tool based on task type, risk level, and tier. It maintains a durable SQLite
ledger of sessions, route decisions, agent results, and verification outcomes. It is not
a chatbot, not a generic wrapper, and not a hosted service. The default configuration
makes no API calls and requires no internet connection.

---

## Architecture constraints

- SQLite is the source of truth. All state lives in `.opencobalt/ledger.db` (and
  `.opencobalt/memories.db`, `.opencobalt/observability.db` for new stores). No
  Postgres, Redis, or external databases for core state.
- The router is deterministic. No LLM is called to decide which tool handles a task.
  Routing is keyword-scored and fully reproducible without API cost.
- No background daemons. OpenCobalt is a CLI that runs and exits. No persistent
  processes, no servers, no startup services.
- All new Python dependencies go in `pyproject.toml`. Optional dependencies go in
  `[project.optional-dependencies]`.
- API adapters (Anthropic, OpenAI, Google) are disabled by default. They require
  explicit configuration via `opencobalt config set api_enabled true`.

---

## Tiered model policy

| Tier | Tools | Task types |
|------|-------|------------|
| executive | Claude Code, Gemini CLI | Architecture, security, final code, public docs, strategy |
| manager | Codex CLI, Cursor, Context7 | Tests, lint, structured cleanup, UI work, editor tasks |
| worker | Ollama (local only) | Summarization, tagging, extraction, rough drafts, local fallback |

Ollama is worker-tier only. It runs on demand, not 24/7. It is never used for
architecture decisions, security review, or public-facing documentation. Never add
Ollama as a required dependency -- it is always optional with graceful fallback.

---

## Safety rules

- Never include credentials, API keys, or tokens in any output file.
- `opencobalt public-check` must pass before any commit or push.
- Never reference private vault paths (e.g., cobaltos-vault) outside of `docs/` or `tests/`.
- Never hardcode real values for secrets -- use `<placeholder>` style in docs.
- Never push to the remote repository unless explicitly instructed.
- Never delete or skip passing tests.
- Never break the SQLite schema without a migration path.

---

## Current working commands

```
opencobalt status            system health
opencobalt route TASK        deterministic task routing
opencobalt history           recent route decisions
opencobalt stats             ledger analytics
opencobalt benchmark         route 10 tasks and show tier breakdown
opencobalt benchmark status  agent leaderboard
opencobalt benchmark record  record a result manually
opencobalt log               append a session event
opencobalt memory status     memory store info (ledger + bridge)
opencobalt memory add        write a memory record
opencobalt memory search     search bridge memory store
opencobalt memory sessions   list session summaries
opencobalt memory export     export memory to markdown
opencobalt context           build context pack
opencobalt verify            run pytest + public-check
opencobalt export            export ledger to markdown
opencobalt doctor            full health check
opencobalt public-check      pre-push safety scan
opencobalt lint              ruff lint
opencobalt agents list       list agents
opencobalt agents run        run a named agent
opencobalt skills list       list skills
opencobalt integrations list list integrations
opencobalt integrations check check integration install status
opencobalt cost status       spend + observability summary
opencobalt cost set-mode     set routing mode
opencobalt cost reset        clear monthly cost records
opencobalt config set/get/list key-value config
opencobalt session start/show/end named work sessions
opencobalt tui               live 4-panel terminal dashboard
opencobalt khoj status       check Khoj sidecar reachability
opencobalt ui                open the React dashboard
```

---

## What NOT to do

- Do not break existing passing tests. The baseline is 214 tests (as of Phase 8).
- Do not push to GitHub without explicit instruction.
- Do not change the SQLite schema without adding migration logic.
- Do not add Postgres, Redis, Qdrant, or any server-side store as a required dependency.
- Do not start Khoj, Ollama, or Docker without being explicitly asked.
- Do not add 24/7 background processes or servers.
- Do not add em dashes to any documentation or comments.
- Do not use hype language in docs or commit messages.
- Do not commit `.env` files, credentials, or private paths.
- Do not use `f-string` or `str.format` with user input for shell commands (injection risk).

---

## Integration status

| Integration | Tier | Status |
|-------------|------|--------|
| claude-code | executive | active if `claude` on PATH |
| gemini-cli | executive | active if `gemini` on PATH |
| codex-cli | manager | active if `codex` on PATH |
| cursor | manager | available (GUI app) |
| context7 | manager | available (MCP server) |
| aider | worker | active if `aider` on PATH |
| ollama | worker | active if ollama running |

---

## Memory system (placeholder -- Phase 3 complete)

Three memory layers:

1. Session memory: `ObservabilitySession` in `.opencobalt/observability.db` tracks
   agent runs, tool calls, cost, and latency within a session.
2. Agent memory: `MemoryBridge` in `.opencobalt/memories.db` persists agent results
   and summaries across sessions with text search.
3. Project knowledge: Khoj (Docker sidecar, localhost:42110) indexes project docs,
   architecture notes, and Obsidian vault entries. Not a core runtime dependency.
   See `docs/KHOJ_INTEGRATION.md` for setup.

All three stores are SQLite-backed or local. No cloud services are required.
