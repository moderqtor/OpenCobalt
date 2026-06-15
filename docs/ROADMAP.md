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

### Phase 18: Autonomous Opportunity Engine v0

- Supervised, local-first opportunity discovery in
  `src/opencobalt/core/opportunity_engine.py` (see `docs/OPPORTUNITY_ENGINE.md`)
- Deterministic goal classification into nine goal classes, extensible track
  library, pluggable local evidence collectors (repo scan, receipts, route history)
- Transparent nine-dimension scoring: risk lowers the total, evidence raises it,
  every contribution is explainable
- Nested delegation trees per track (strategist -> researcher -> specialists ->
  receipt-verifier) with enforced depth, risk ceilings, and permission scopes
- Plans never auto-execute; risky steps stay pending behind the existing policy gate
- Outcome tracking table (`useful` / `neutral` / `wasted` / `abandoned`) as the
  training signal for future learned routing
- Bounded evaluator loop primitive (`core/evaluator_loop.py`): propose, evaluate,
  mutate, keep best -- max iterations, timeout, local evaluators only, receipts
- CLI: `opencobalt opportunities brainstorm/score/report/plan/list/outcome`

### Phase 19 (part 1): Approval Bridge + Provenance Loop v1

- Approval bridge (`core/approval_bridge.py`): promote opportunity tracks/plans
  into persisted approval requests with per-step risk and approval state
  (pending / approved / rejected / executed / failed / superseded)
- Green steps auto-approve only when policy allows; yellow/red require explicit
  approval; black is blocked with no override
- Execution handoff goes through the existing policy-gated execution engine
  unchanged (dry-run default, `--execute`, `--execute --yes` for red); every
  step links its execution plan and receipt back to the approval
- Provenance layer (`core/provenance.py`) and `opencobalt why <ANY_ID>`: lineage
  from goal to evidence, score, plan, approval, execution, receipt, artifact,
  and outcome, for any id, read-only
- Outcome feedback: `approvals outcome` records receipt-evidenced outcomes on
  the underlying track
- CLI: `approvals list/show/approve/reject/run/outcome`,
  `opportunities approve`, `why`; status shows pending approvals and latest
  receipt verification
- Polish: `strategy` goal class, idempotent `opportunities plan` (`--new` to
  force), noop adapter normalizes echo-prefixed tasks

### Phase 19 (part 2): Outcome-weighted scoring + collector interface

- Outcome-weighted scoring: recorded useful/wasted/abandoned outcomes nudge
  track scores by a bounded, explained amount (`outcome_adjustment`, capped
  at +/-0.1, one explanation line per adjustment)
- `OpportunityStore.outcome_stats_by_track_type()` joins outcomes to track
  types as the structured signal for future learned routing
- Web research evidence collector behind the `EvidenceCollector` protocol:
  disabled by default, performs no I/O without an explicitly injected
  fetcher; tests use fakes only

### Phase 20: Evolve Mode v0 (supervised self-improvement)

- `src/opencobalt/core/evolve.py` (see `docs/EVOLVE_MODE.md`): missions,
  candidates, explainable self-improvement scoring with wrapperware escape
  value, roadmap proposals, analysis-only subagent fanout
- Candidates are opportunity tracks: approval, policy-gated execution,
  receipts, provenance, and outcomes reuse the existing systems unchanged
- CLI: `opencobalt evolve start/report/candidates/approve/run/roadmap/list`;
  `/evolve` in the shell; `why` covers missions and candidates
- Roadmap writes gated behind explicit `--write`; append-only and idempotent
- Hard boundaries: no self-replication, no auto-merge/push, no network,
  no spend/credential paths, no policy-gate bypass

### Phase 21: Mission State Machine v1

- Durable mission spine (`core/mission_engine.py`, see `docs/MISSIONS.md`):
  missions (`mis-`), mirrored mission steps (`mstp-`), append-only mission
  events (`mev-`, enforced by SQLite triggers)
- One lifecycle across the existing systems: discovery (opportunity or
  evolve), selection, plan promotion, approval-backed steps, policy-gated
  execution, receipts, verification, provenance, outcome feedback
- `missions advance` moves one safe stage and stops at approval
  boundaries; execution only via `missions run-step --execute`
- Risk budgets (`--max-risk`) only tighten the existing gates; black
  remains blocked with no override; red still needs `--execute --yes`
- Evolve missions are a mission type, not a separate universe: evolve
  candidates back mission selection and keep receipt/outcome linkage
- `why` resolves `mis-`/`mstp-` ids through the same provenance builder
- CLI: `missions start/list/show/advance/approve-step/run-step/outcome/why`

### Phase 22: Adapter Receipt Normalization v1

- Normalized adapter contract in `src/opencobalt/execution/`: capability
  discovery, bounded invocation, policy boundary, event stream, artifact
  capture, normalized receipt metadata, verification, provenance references,
  and outcome-ready receipt ids.
- Existing execution adapters (`noop`, `ollama`, `google-antigravity`) emit
  `RuntimeCapabilitySnapshot`, `NormalizedInvocation`, and
  `NormalizedAdapterReceipt` metadata through the existing `WorkReceipt`.
- `opencobalt adapters list` and `opencobalt adapters inspect` expose adapter
  availability, limitations, capability snapshot hashes, and verifiability
  levels.
- `receipts inspect`, `receipts verify`, mission receipt linkage, and `why`
  traces surface adapter id, invocation hash, capability snapshot hash,
  artifact hash counts, and verifiability without adding a parallel receipt or
  provenance system.
- Missing runtimes are unavailable, skipped, and auditable. Weak or
  unverifiable adapters are marked limited, not trusted.

### Phase 23: Cursor Runtime Adapter v0

- Cursor is an execution runtime only through the normalized adapter receipt
  contract. It appears in `opencobalt adapters list` and
  `opencobalt adapters inspect cursor`.
- Capability discovery checks real PATH executables and common macOS
  `Cursor.app` locations. It inspects `cursor agent --help` before claiming
  non-interactive support.
- Safe execution is limited to `cursor agent --print --mode plan
  --output-format text -- "task"` through `ExecutionEngine`, with policy gates,
  stdout/stderr artifact capture, hash verification, normalized receipts,
  provenance metadata, and outcome-ready receipt ids.
- Cursor remains partial, not full, because Cursor credentials, account state,
  network behavior, and read-only enforcement live outside OpenCobalt. If the
  local agent CLI is absent, Cursor is unavailable or discovery-only.
- Cloud mode, force, browser automation, MCP auto-approval, login, logout,
  deploy, publish, spend, message, and API-key paths are not enabled.

### Phase 24: Claude Code Runtime Adapter v0

- Claude Code is an execution runtime only through the normalized adapter
  receipt contract. It appears in `opencobalt adapters list` and
  `opencobalt adapters inspect claude-code`.
- Capability discovery checks a real PATH executable, then local
  `claude --version` and `claude --help` evidence before claiming runtime
  support.
- Safe execution is limited to `claude --print --output-format text
  --permission-mode plan` through `ExecutionEngine`, with policy gates,
  stdout/stderr artifact capture, hash verification, normalized receipts,
  provenance metadata, and outcome-ready receipt ids.
- Claude Code remains partial, not full, because credentials, account state,
  network behavior, model behavior, and internal permission enforcement live
  outside OpenCobalt. If safe headless invocation is absent, support is partial
  and discovery-only.
- Dangerous permission bypass, unrestricted tools, credential, auth, token,
  browser-control, deploy, publish, spend, message, and MCP auto-approval paths
  are not enabled.
- Keep validating this adapter against local `claude --help` evidence as the
  Claude Code CLI evolves.

### Phase 25: Codex Runtime Adapter v0

- Codex CLI is an execution runtime only through the normalized adapter receipt
  contract. It appears in `opencobalt adapters list` and
  `opencobalt adapters inspect codex-cli`.
- Capability discovery checks a real PATH executable, then local
  `codex --version`, `codex --help`, and `codex exec --help` evidence before
  claiming runtime support.
- Safe execution is limited to `codex --sandbox read-only
  --ask-for-approval never exec` through `ExecutionEngine`, with policy gates,
  stdout/stderr artifact capture, hash verification, normalized receipts,
  provenance metadata, and outcome-ready receipt ids.
- Codex remains partial, not full, because credentials, account state, network
  behavior, model behavior, and internal permission enforcement live outside
  OpenCobalt. If safe headless invocation is absent, support is partial and
  discovery-only.
- Dangerous approval/sandbox bypass, danger-full-access sandbox, credential,
  auth, token, login, logout, MCP management, app-server, remote-control, cloud,
  apply, update, browser-control, deploy, publish, spend, message, and web
  search paths are not enabled.
- Keep validating this adapter against local `codex --help` and
  `codex exec --help` evidence as the Codex CLI evolves.

## In Progress / Next

Direction note: OpenCobalt is a trust, control, provenance, and
orchestration layer, not wrapperware. Adding "support for tool X" is not a
goal by itself and shallow adapter work is rejected. Every future adapter
must arrive as a full loop: capability discovery -> normalized receipt
contract -> artifact capture -> policy boundary -> provenance edge ->
outcome feedback. An adapter that cannot produce verifiable receipts and
provenance edges does not ship.

### Adapter and evidence loops

- adapter-routing-from-outcomes-v1: start selecting runtimes from receipt
  outcomes and verification history, not just deterministic keyword scores.
- future-runtime-adapters: every future adapter (`codex-cli`, `aider`,
  `continue`, and additional local runtimes) must satisfy the normalized
  receipt contract before it can execute work. Legacy Gemini CLI names remain
  aliases to `google-antigravity`, not a new adapter family.
- web-research-evidence-collector-v0: a live fetcher for the existing
  `EvidenceCollector` protocol. Explicit configuration required, off by
  default, every fetch logged as evidence with source and strength, no
  background crawling.

### Safety hardening backlog

- mission-outcome-status-guard: require `missions outcome` to run only from
  `awaiting_feedback` unless an explicit repair mode is added. Mission
  outcomes are already receipt-evidenced and traceable; this would make the
  lifecycle harder to misuse.

### Mission depth

- evolve-long-running-missions-v1: multi-cycle evolve missions that reuse
  Mission State Machine v1 (propose -> score -> plan -> approve -> execute
  -> verify -> learn, repeated across cycles with durable mission events).
- learned routing from outcomes: extend bounded outcome-weighted scoring
  from track selection into runtime selection. Weights stay capped and
  explainable; no hidden self-modifying state.
- self-upgrade-pr-automation-v0: an approved evolve candidate can prepare
  a local branch, commits, and a PR draft as artifacts behind explicit
  approval. No auto-merge, no push without instruction, receipts for every
  step.
- long-running supervised autonomy: a legitimate "make useful progress
  while I'm away" mode. It may gather evidence, score opportunities,
  generate candidates, prepare plans, run safe dry-runs, queue approvals,
  verify local artifacts, and summarize blocked decisions. It never
  crosses an approval boundary and never spends, deploys, publishes, or
  messages. Everything it does is replayable from receipts and why traces.

### Surfaces

- provenance graph visualization: render the existing why-trace graph
  (nodes and edges already exist) in the TUI and desktop UI.
- desktop-control-room-prototype-v0: a desktop surface over missions,
  approvals, receipts, and provenance. A control room for bounded
  autonomy, not a chat window.

### capital-mission-envelope-v0 (design only)

A future mission type for capital allocation research. Design constraints,
all mandatory:

- watch-only wallet state; OpenCobalt never holds keys
- explicit budget caps declared up front, enforced as a mission risk budget
- opportunity research and risk scoring through the existing engines
- simulations and dry-runs only; every projection is an artifact
- unsigned transaction proposals as artifacts; a human signs elsewhere
- human approval for every step; receipts and outcome tracking throughout
- no custody of seed phrases or private keys, ever
- no autonomous spending path exists, even behind flags

### Phase 21 (continued): Loop depth and surfaces

- UI panels for opportunity tracks, subagent trees, evidence, and approval state
- Evaluator-driven discovery on bounded local domains (routing keywords,
  benchmark heuristics) with full receipts
- Bounded code-editing execution adapters behind the same approval gates
- Explicitly configured live web research fetcher for the collector interface
- Outcome-weighted routing: extend outcome weighting from scoring into
  runtime selection

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
