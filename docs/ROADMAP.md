# Roadmap

## Product Vision

OpenCobalt is a local-first AI orchestration control plane that unifies routing, memory, context
compilation, agent management, benchmarking, and integration across AI coding tools.

Core thesis: autonomous task routing with verifiable results across tiered agents. Not a chatbot
wrapper. Not an API aggregator for personal use. Not a terminal emulator.

All routing is deterministic. All state is SQLite. All defaults are local and offline.

Optional hosted mode (rate-limited subscriptions, public-facing routing layer) is a future phase
that does not change the local-first default.

---

## Completed

### Phase 1: Core MVP

- Clean public repo scaffold
- Pydantic models for all domain objects
- SQLite ledger: events, verification results, route decisions, memory records
- Deterministic keyword-based router with tier classification
- Ollama model discovery with graceful fallback
- Context pack compiler
- Public safety scanner
- Memory store with markdown export
- Verification runner (pytest + public-check)
- Typer CLI with all primary commands
- 58 passing tests
- Architecture, routing, memory, and safety docs

### Phase 2: Modular Systems

- Cost module with per-model cost estimates
- Agents registry and base agent class
- Skills registry (file-reader, diff-writer)
- Integrations registry (aider, ollama)
- UI shell scaffold (React + Tailwind)
- CI pipeline (GitHub Actions)

### Phase 3: Real Integration

- Ollama subprocess invocation in agents (real model calls, not stubs)
- Route decision logging to ledger
- `history`, `benchmark`, `config`, and `export` commands
- 4-panel TUI with live status display

### Phase 4: Analytics and Depth

- `stats` command with routing analytics
- `memory add` command
- `log-list` command
- `route --verbose` and `route --estimate` flags
- `context --summarize` flag
- CLI integration tests
- CHANGELOG

### Phase 5: Quality and Lint

- Ruff added to CI
- Session tracking (start, stop, show, list)
- Improved `doctor` command with structured checks
- ARCHITECTURE documentation rewrite

### Phase 6: Agent and Skill Integration

- `code-reviewer` agent uses `file-reader` skill for real file metrics
- Session tagging in route decisions
- 174 passing tests

### Phase 7: Benchmarking, Integration Library, and Skill Registry

- Agent benchmarking store (BenchmarkRecord + BenchmarkStore, SQLite-backed)
- Leaderboard with composite score: win_rate * 0.6 + speed_score * 0.4
- `benchmark status` and `benchmark record` subcommands
- 6 integrations: aider, ollama, claude-code, gemini-cli, cursor, context7
- Each integration declares tier, capabilities, and integration_status
- `integrations check` command: runs install_check() on all, reports active/inactive
- 3 skills: file-reader, diff-writer, context-injector
- Each skill declares `compatible_agents`; each agent declares `compatible_skills`
- `skills list [--agent NAME]` command
- `cost reset` command: clears current month cost records
- 191 passing tests

---

### Phase 8: Live UI and API Server

- UI backend bridge: React dashboard wired to FastAPI via REST API
- FastAPI server on port 8000, Vite dev server on port 5173; both start via `opencobalt ui`
- `context-diff` command (shows what changed since the last context build)
- 244 passing tests

---

## In Progress / Next

- API adapter layer: Anthropic, OpenAI, and Google adapters with per-call cost tracking
- Router integration with benchmark data: `get_best_for_task_type()` replaces static tier rules for
  agents with sufficient benchmark history
- Obsidian export write path
- DesignLab / Visual Compiler

---

## Future: Optional Hosted Mode

When local routing has enough benchmark history, the system can expose a routing API:
- Rate-limited subscriptions with per-token billing
- Public-facing routing layer that aggregates benchmark results across installs
- Optional agent execution (not just routing and logging) via managed API calls

This is a future phase. The local-first default never changes.

---

## Not in Scope

- Autonomous agent execution without human direction
- Multi-user or server mode in the local version
- Vendor lock-in to any single AI provider
