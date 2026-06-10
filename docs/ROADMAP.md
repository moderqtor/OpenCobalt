# Roadmap

## Product Vision

OpenCobalt is a local-first AI orchestration control and provenance layer that unifies
routing, memory, context compilation, agent management, benchmarking, artifact receipts,
and integration across AI agent runtimes.

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
- Pytest coverage for the first core workflows
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
- Expanded pytest coverage

### Phase 7: Benchmarking, Integration Library, and Skill Registry

- Agent benchmarking store (BenchmarkRecord + BenchmarkStore, SQLite-backed)
- Leaderboard with composite score: win_rate * 0.6 + speed_score * 0.4
- `benchmark status` and `benchmark record` subcommands
- Canonical integrations include aider, ollama, claude-code, google-antigravity,
  cursor, context7, GitHub CLI, and Obsidian
- Each integration declares tier, capabilities, and integration_status
- `integrations check` command: runs install_check() on all, reports active/inactive
- 3 skills: file-reader, diff-writer, context-injector
- Each skill declares `compatible_agents`; each agent declares `compatible_skills`
- `skills list [--agent NAME]` command
- `cost reset` command: clears current month cost records
- Expanded integration and skill coverage

---

### Phase 8: Live UI and API Server

- UI backend bridge: React dashboard wired to FastAPI via REST API
- FastAPI server on port 8000, Vite dev server on port 5173; both start via `opencobalt ui`
- `context-diff` command (shows what changed since the last context build)
- UI and API coverage added

---

### Phase 9: Bug Fixes + Functional Command Center

- Fix Receipts panel: replace hardcoded mock data with real `/api/receipts` endpoint backed by ledger
- Fix Command Center: real `<input>` that POSTs to `/api/route`, shows routing result inline
- Fix CORS to allow POST for the route endpoint
- CLI startup splash: animated ASCII hexagonal logo (Rich-based, comparable to modern agent CLIs)
- Optional prompt refinement via Ollama before routing (graceful no-op if Ollama absent)
- Session-scoped git branch (`oc/YYYY-MM-DD-session`) created on shell start if tree is clean

---

### Phase 10: Desktop App + Routing Visualization

- Replace localhost React UI with a standalone desktop app (Tauri recommended: ~8MB, no Node runtime)
- Animated node-graph routing visualization: nodes pulse to life as routing decisions are made,
  edges carry simulated "electricity" between tools (ComfyUI-style but cleaner)
- Each active agent/tool gets a live card with token usage, progress, and click-to-expand details
- Routing animation plays every time a task is dispatched from the Command Center

### Phase 11: Multi-Agent Orchestration

- Orchestration DSL: `/orch "task"` and `/orch "task" -> [claude:impl, codex:tests] -> merge`
- `TaskDecomposer`: keyword-based split into typed subtasks (impl, tests, docs, review, analyze, summarize)
- `SubagentRegistry`: 6 specialized agents (impl-agent, test-gen, doc-writer, security-reviewer, analyst-agent/google-antigravity, summarizer/ollama)
- `OrchestrationExecutor`: parallel fan-out via dedicated `BackgroundRunner(max_workers=6)`
- `MultiRouteDecision` model and ledger table for full fan-out audit trail
- `BenchmarkRecord` extended with `subagent_id` and `prompt_style` columns
- `opencobalt orch TASK` CLI command
- Multi-route hint in shell when task spans multiple tiers

### Phase 12: Connector Expansion

- Prompt splitting: decompose a task into N subtasks, dispatch each to the best-fit tool in parallel
- Cross-agent communication protocol: Claude + Codex can exchange sub-results within one session
- Specialized subagent registry: agents tuned per task type (code review, refactor, test gen, docs)
- Subagent benchmarking: track performance per subagent type, not just per top-level tool
- Prompt style benchmarking: track which prompt forms produce the best results per model

### Phase 16: Receipt-Backed Execution v0

- Execution layer in `src/opencobalt/execution/`: plan, policy gate, safe
  process runner, runtime adapters (google-antigravity, ollama, noop)
- Every run writes a work receipt with command plan, capability snapshot,
  and SHA-256 hashed output artifacts
- Policy gate: dry-run always allowed, green/yellow need `--execute`,
  red needs `--execute --yes`, black blocked
- CLI: `opencobalt run`, `receipts list/inspect/verify`,
  `artifacts attach/verify/list`
- Structured execution event stream (JSONL) as the TUI/UI foundation
- Docs: `docs/EXECUTION_LAYER.md`, `docs/ARTIFACT_RECEIPTS.md`

## In Progress / Next

### Phase 17: Execution Layer v1

- `opencobalt execute --plan <plan_id>` to resume stored plans
- Multi-step plans with per-step policy checks
- Adapters for claude-code, codex-cli, aider
- Semantic verification of receipts (did the output answer the task)
- TUI panel reading the execution event stream

### Phase 12: Connector Expansion

- Obsidian (read/write vault notes via vault path config)
- GitHub (PR creation, issue linking, auto-commit on route completion)
- Google Antigravity CLI (`agy`) runtime discovery, legacy Gemini CLI alias migration, and artifact ingestion foundation
- Supabase (project-level logging of route decisions to a remote table, optional)
- Additional connectors: Cursor Composer, Continue.dev, Windsurf

---

## End Goal: AI Powerhouse

OpenCobalt's long-term vision is to be the most capable local AI orchestration layer available:
- Every prompt is refined before routing
- Every route is animated and observable
- Every agent result is verified, logged, and benchmarked
- Multiple agents collaborate on the same task simultaneously
- The system learns which agents perform best per task type and routes accordingly
- All of this runs locally with no vendor lock-in and no persistent background daemons

The "neuron" model: each subagent is a neuron; the routing layer is the synaptic network.
As benchmark data accumulates, routing becomes increasingly data-driven rather than rule-based.

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
