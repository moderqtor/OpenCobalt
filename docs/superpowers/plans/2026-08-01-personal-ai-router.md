# Personal AI Router v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a restart-safe local Chat application that selects and executes an inspectable provider/persona route through OpenCobalt receipts.

**Architecture:** A focused `opencobalt.personal_ai` package owns chat-domain persistence, persona policy, provider normalization, deterministic routing, orchestration, and a typed FastAPI router. It references the existing shared SQLite ledger, `ExecutionEngine`, `WorkReceipt`, `MissionStore`, approval policy, and skill registry. The React application consumes only the typed personal-AI contracts.

**Tech Stack:** Python 3.11+, Pydantic 2, SQLite, FastAPI, Typer, React 18, Vite 5, CSS, existing ExecutionEngine runtime adapters.

## Global Constraints

- All real or simulated runtime execution flows through `ExecutionEngine`.
- No push, merge, deploy, publish, credential access, paid service, outbound telemetry, or implicit cloud fallback.
- SQLite changes are additive, foreign-keyed, idempotent, and preserve existing user data.
- Provider executable presence, authentication, and successful invocation are separate states.
- Local-only mode excludes every network-requiring provider before selection.
- Historical routes reference an immutable persona version and normalized work receipt.
- New behavior follows a witnessed red-green-refactor cycle.
- Final gates are `.venv/bin/ruff check .`, `.venv/bin/opencobalt public-check`, `.venv/bin/pytest`, and `npm run build --prefix ui`.

---

### Task 1: Durable chat and persona domain

**Files:**
- Create: `src/opencobalt/personal_ai/models.py`
- Create: `src/opencobalt/personal_ai/store.py`
- Create: `src/opencobalt/personal_ai/personas.py`
- Create: `src/opencobalt/personal_ai/__init__.py`
- Test: `tests/test_personal_ai_store.py`
- Test: `tests/test_personas.py`

**Interfaces:**
- Produces: `PersonalAIStore(db_path)`, `Conversation`, `ChatMessage`, `Persona`, `PersonaVersion`, `AISettings`, `RouteRecord`, `RouteCandidate`, `ChatExecution`, `MemoryEntry`, and `SkillRecord`.
- Produces: `ensure_builtin_personas(store)`, `render_persona_policy(version, cognitive_policy)`, and `duplicate_persona(store, persona_id, name)`.

- [ ] Write persistence tests that create an old `Ledger`, initialize `PersonalAIStore`, assert every new table and foreign key, persist/reload conversations and messages after constructing a second store, and prove persona versions remain immutable.
- [ ] Run `.venv/bin/pytest tests/test_personal_ai_store.py tests/test_personas.py -v` and confirm failure because the package does not exist.
- [ ] Implement typed models, additive schema migration `personal_ai_schema_versions`, named-column statements, CRUD methods, and built-in persona seeding.
- [ ] Run the targeted tests and confirm pass.
- [ ] Run `.venv/bin/ruff check src/opencobalt/personal_ai tests/test_personal_ai_store.py tests/test_personas.py`.

### Task 2: Provider normalization and engine-backed adapters

**Files:**
- Create: `src/opencobalt/personal_ai/providers.py`
- Create: `src/opencobalt/personal_ai/mock_runtime.py`
- Modify: `src/opencobalt/execution/adapters.py`
- Test: `tests/test_personal_ai_providers.py`

**Interfaces:**
- Consumes: `PersonalAIStore`, `ProviderRequest`, `ProviderEvent`.
- Produces: `ChatProvider`, `ProviderStatus`, `ProviderRegistry.discover()`, `ProviderRegistry.get(provider_id)`, and engine-backed Mock, Ollama, Codex, Antigravity, Claude, and discovery-only Gemini profiles.

- [ ] Write tests proving executable discovery does not imply authentication, no model names are fabricated, Ollama models are injected from discovery, every execution calls a fake `ExecutionEngine`, mock output streams deterministically, cancellation stops chunks, and dangerous flags never appear.
- [ ] Run `.venv/bin/pytest tests/test_personal_ai_providers.py -v` and confirm the missing contract fails.
- [ ] Implement the normalized contract, mock runtime adapter, capability mapping, bounded output decoding, usage normalization, and categorized errors.
- [ ] Run provider tests and existing `tests/test_execution_layer.py tests/test_antigravity_integration.py`.
- [ ] Run Ruff on changed Python files.

### Task 3: Deterministic chat router

**Files:**
- Create: `src/opencobalt/personal_ai/router.py`
- Test: `tests/test_personal_ai_router.py`

**Interfaces:**
- Consumes: `RouteRequest`, `PersonaVersion`, `ProviderStatus`, `AISettings`, historical outcomes.
- Produces: `classify_task(text)`, `classify_privacy(text, mode)`, and `AIRouter.plan(request, persona, providers) -> RoutePlan`.

- [ ] Write literal, table-driven tests for all task classes, serious-task Ollama exclusion, local-only hard filtering, unavailable manual override, provider/persona affinity, provider-native mismatch disclosure, cost and latency categories, selected skills/tools, verification strategy, and named score components.
- [ ] Run `.venv/bin/pytest tests/test_personal_ai_router.py -v` and confirm missing behavior fails.
- [ ] Implement explicit rules and integer heuristic components; label totals as heuristic points rather than probabilities.
- [ ] Run router tests and existing `tests/test_router.py tests/test_auto_orchestrator.py`.

### Task 4: Traceable chat execution lifecycle

**Files:**
- Create: `src/opencobalt/personal_ai/service.py`
- Test: `tests/test_chat_service.py`

**Interfaces:**
- Consumes: store, personas, provider registry, `AIRouter`, `ExecutionEngine`.
- Produces: `ChatService.create_conversation`, `ChatService.stream_request`, `ChatService.cancel`, `ChatService.rerun`, `ChatService.compare`, and `ChatService.promote_to_mission`.

- [ ] Write service tests for the 19 lifecycle stages: user message, classification, route/candidates, explicit no-fallback, visible fallback when enabled, normalized events, assistant persistence, receipt linkage, restart persistence, provider error categories, cancellation, rerun lineage, comparison, and explicit-only memory proposals.
- [ ] Run `.venv/bin/pytest tests/test_chat_service.py -v` and confirm failure before implementation.
- [ ] Implement the generator lifecycle with append-only stream events, durable cancellation state, redacted failures, WorkReceipt linkage, and mission promotion through `MissionEngine` without execution.
- [ ] Run service tests plus `tests/test_execution_layer.py tests/test_mission_engine.py`.

### Task 5: Curated memory and secure local skill import

**Files:**
- Create: `src/opencobalt/personal_ai/skill_import.py`
- Test: `tests/test_personal_ai_memory.py`
- Test: `tests/test_skill_import_security.py`

**Interfaces:**
- Produces: `SkillImportService.preview(source)`, `SkillImportService.install(preview_hash, approved)`, memory create/update/delete/pin methods, and ledger event receipt ids.

- [ ] Write tests that reject traversal, symlinks, oversized manifests and inventories, detect executable content/permissions, require approval for meaningful risk, pin exact tree hashes, avoid execution, support rollback removal, and keep raw conversations distinct from curated memory.
- [ ] Run the two test files and confirm the absent feature fails.
- [ ] Implement bounded inspection/copying and explicit curated-memory lifecycle.
- [ ] Run the two test files and Ruff.

### Task 6: Typed personal-AI API

**Files:**
- Create: `src/opencobalt/personal_ai/api.py`
- Modify: `src/opencobalt/api_server.py`
- Test: `tests/test_personal_ai_api.py`
- Modify: `tests/test_api_server.py`

**Interfaces:**
- Produces endpoints under `/api/v1`: conversations/messages, chat stream/cancel/rerun/compare, routes, personas, providers/health/models, skills/import, memory, missions, ledger/receipts, settings/export.

- [ ] Write API contract tests for validation, NDJSON event order, cancellation, route detail, persona versioning, provider redaction, CRUD actions, compatibility endpoints, and CORS/local relative URLs.
- [ ] Run `.venv/bin/pytest tests/test_personal_ai_api.py tests/test_api_server.py -v` and confirm new endpoints return 404.
- [ ] Implement a FastAPI `APIRouter`, exception normalization, bounded list limits, and compatibility includes.
- [ ] Run API tests and Ruff.

### Task 7: Chat-first React application

**Files:**
- Create: `ui/src/api.js`
- Create: `ui/src/Markdown.jsx`
- Create: `ui/src/components.jsx`
- Replace: `ui/src/App.jsx`
- Replace: `ui/src/index.css`
- Modify: `ui/src/main.jsx`

**Interfaces:**
- Consumes: relative `/api/v1` routes and NDJSON events.
- Produces: Chat, Routes, Missions, Skills, Memory, Ledger, Providers, and Settings pages with a responsive route inspector.

- [ ] Implement the Iron/Graphite/Fog/Cobalt/Amber token system, system/dark/light themes, full text navigation, accessible focus states, reduced motion, and responsive drawers.
- [ ] Implement conversation creation/selection, persisted persona and controls, composer keyboard behavior, stream rendering, cancellation, errors, route spine/inspector, rerun, compare, and local-only state.
- [ ] Implement data-backed supporting pages and truthful empty/unavailable states with no fake metrics or placeholder charts.
- [ ] Run `npm run build --prefix ui`; fix every production build error.
- [ ] Run `git diff --check` and review rendered desktop/mobile screenshots before claiming visual validation.

### Task 8: Startup, documentation, and full verification

**Files:**
- Modify: `README.md`
- Modify: `ui/README.md`
- Create: `docs/PERSONAL_AI_ROUTER.md`
- Modify: `src/opencobalt/cli.py` only if startup defects are found by smoke.

**Interfaces:**
- Produces: verified `opencobalt ui` startup, provider setup/status guide, data paths, safe reset guidance, and exact validation receipts.

- [ ] Document prerequisites, setup, data, Ollama, Codex, Antigravity, optional credentials boundary, launch, tests, provider troubleshooting, export, and safe reset.
- [ ] Run targeted tests, then `.venv/bin/ruff check .`, `.venv/bin/opencobalt public-check`, `.venv/bin/pytest`, and `npm run build --prefix ui`.
- [ ] Start `opencobalt ui --no-browser`, verify backend/frontend reachability, complete a real or development chat, inspect route and WorkReceipt rows, restart, and confirm conversation persistence and local-only/persona separation.
- [ ] Perform browser-visible desktop and narrow-width review when browser automation is available; record exactly what was and was not inspected.
- [ ] Run `git status -sb`, `git log --oneline`, and `git diff --check`; create logical local commits only after public safety is clean. Do not push or merge.
