# Roadmap

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
- Skills registry
- Integrations registry
- UI shell scaffold
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

- `code-reviewer` agent uses `file-reader` skill for real file metrics (line count, function count, complexity)
- Session tagging in route decisions
- 174 passing tests

---

## In Progress / Next

- UI backend bridge -- wire React dashboard to Python via WebSocket or simple HTTP API
- API adapter layer -- Anthropic, OpenAI, and Google adapters with per-call cost tracking
- `context diff` command -- show what changed between context packs
- Obsidian export write path
- DesignLab / Visual Compiler

---

## Not in Scope

- Autonomous agent execution (OpenCobalt routes and logs; it does not run agents without human direction)
- Multi-user or server mode
- Vendor lock-in to any single AI provider
