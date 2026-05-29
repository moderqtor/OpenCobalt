# Phase 0 Audit: Initial Snapshot

**Date:** 2026-05-28
**Auditor:** Claude Code (Sonnet 4.6)
**Repo:** ~/dev/OpenCobalt
**Source:** ~/dev/AI (private Cobalt Forge repo)
**Status:** READ-ONLY. No implementation has begun.

---

## 1. Environment

| Item | Value |
|------|-------|
| Working directory | ~/dev/OpenCobalt |
| Git status | Not a git repo yet |
| Python | 3.14.4 |
| Node | v25.5.0 |
| npm | 11.8.0 |
| Ollama: llama3:latest | 4.7 GB (confirmed) |
| Ollama: mistral:latest | 4.4 GB (confirmed) |
| phi3:latest | NOT installed (stale references exist in source) |

---

## 2. Source Repo Status (~/dev/AI)

The private Cobalt Forge repo is a mature, active codebase. Top-level structure:

```
~/dev/AI/
  core/               Shared library: brain.py, config.py, memory.py, knowledge.py,
                      graph.py, crew.py, models.py, vault.py
  automation/lib/     Engineering control plane: events.py, economic_router.py,
                      eval_court.py, goal_compiler.py, supervisor_queue.py,
                      worker_execution.py, plugin_gateway.py, plugin_sandbox.py,
                      agent_inventory.py, self_improvement.py, codex_exec_adapter.py
  subsystems/         adversarial-ideation, agent-memory, mcp-vault-logger,
                      orchestrator, parliament, selfmod, synthesis, ideation
  ai/                 Canonical docs: MASTER_CONTEXT.md, ROADMAP.md,
                      AUTONOMY_POLICY.md, DOCS_SOURCE_OF_TRUTH.md, ARCHITECTURE.md,
                      TOOL_ROUTING.md, AGENT_REGISTRY.md, SKILL_REGISTRY.md
  agents/             Agent definitions per tool
  logs/               4,579 files (private session data, crew runs, events)
  memory_store/       cobalt.db JSONL, fallback_memories.jsonl
  vault_index/        ChromaDB index of personal Obsidian vault
  node_modules/       Third-party JS (do not copy)
```

Document hierarchy (per ai/DOCS_SOURCE_OF_TRUTH.md):
  ai/MASTER_CONTEXT.md > ai/ROADMAP.md > ai/AUTONOMY_POLICY.md > feature docs
  Root-level docs (TOOL_ROUTING.md, SECURITY_MODEL.md) are redirect stubs only.

---

## 3. Detected Ollama Models

Only these two models are confirmed installed:

- llama3:latest (365c0bd3c000, 4.7 GB)
- mistral:latest (6577803aa9a0, 4.4 GB)

Stale references to phi3:latest exist in:
- ~/dev/AI/CLAUDE.md (OBSERVER_MODEL default)
- Any subsystem config that references phi3

Action required: all OpenCobalt config, docs, and tests must use dynamic
model discovery or reference only llama3/mistral by name.

---

## 4. Third-Party Repos (~/dev/git-repos)

26 repos cloned. Classification by value to OpenCobalt:

### Core inspiration / optional adapters (worth documenting in CREDITS.md)
- pydantic-ai: typed agent framework, Pydantic-native
- instructor: structured LLM outputs via Pydantic
- mem0: cross-session memory layer patterns
- dspy: programmatic LM / prompt optimization patterns
- MoA-Ollama-Chat: mixture-of-agents with Ollama
- Multi-Agents-Debate / llm-council: adversarial multi-agent patterns
- GraphReasoning: graph-based reasoning patterns
- SciAgentsDiscovery: scientific multi-agent orchestration patterns
- self_improving_coding_agent: SICA self-improvement loop patterns
- storm: long-form synthesis agent patterns
- gepa: evolutionary prompt adaptation
- mapper-mo: reasoning/mapping patterns

### Research / future integration (low priority now)
- AI-Scientist: autonomous research loop (heavy infra)
- crewAI: multi-agent orchestration (heavy dependency)
- llama_index: retrieval indexing
- graphrag: graph RAG (heavy)
- gpt-researcher: web research
- agentops: observability hooks

### Drop from roadmap (not aligned with current scope)
- autogen: complex framework, high maintenance burden
- ADAS: automotive / unrelated
- khoj: requires PostgreSQL + heavy infra
- SWE-agent: automated SWE benchmarking
- txtai: search platform
- openevolve: code evolution
- e2b: cloud sandboxes
- agentops: observability (optional later, not now)

Do not vendor any of these repos into OpenCobalt. Reference by documentation and
optional adapter interfaces only.

---

## 5. Candidate Files for Clean Extraction

### SAFE TO COPY (after review, no secrets found in these files)

| Source | Target | Notes |
|--------|--------|-------|
| automation/lib/events.py | src/opencobalt/core/events.py | Clean append-only event spine. No secrets. Minor path adaptation needed. |
| automation/lib/economic_router.py | src/opencobalt/core/router.py | Sophisticated deterministic routing. No secrets. Needs schema adaptation for new models. |
| core/models.py | src/opencobalt/core/models.py | Pydantic models (partial). Useful as schema reference, will be rewritten with new schema. |
| STITCH.md | docs/DESIGN_SYSTEM.md | Excellent design system spec. Needs rename/reframe for OpenCobalt identity. |
| ai/AUTONOMY_POLICY.md | docs/TOOL_ROUTING.md | Green/yellow/red zone doctrine is excellent. Rewrite, do not dump. |

### REWRITE INSPIRED BY (do not copy text verbatim)

- ai/MASTER_CONTEXT.md: architecture doctrine, control plane framing
- ai/ROADMAP.md: phasing approach, status language
- ai/AUTONOMY_POLICY.md: autonomy zones

### DO NOT COPY

| File/Folder | Reason |
|-------------|--------|
| NEXT_STEPS.md | Contains Neo4j password, khoj admin credentials, personal email |
| subsystems/.env | Secrets file |
| subsystems/agent-memory/.env | Secrets file |
| subsystems/adversarial-ideation/.env | Secrets file |
| core/config.py | Line 80 has hardcoded NEO4J_PASSWORD default "cobalt2026" |
| logs/ | 4,579 files, private session data, raw prompts, personal info |
| memory_store/ | Private JSONL memories and cobalt.db |
| vault_index/ | ChromaDB index of personal Obsidian vault |
| node_modules/ | Third-party JS, not vendored |
| __pycache__/ | Generated bytecode |
| core/memory.py | References private vault paths and ChromaDB |
| core/knowledge.py | References private vault and ChromaDB index |
| core/brain.py | References ANTHROPIC_API_KEY, OpenAI key (no hardcoded values, but too coupled to private infra) |

---

## 6. Public Safety Risks

### CRITICAL (blockers before any public push)

1. NEXT_STEPS.md contains:
   - Neo4j password in plaintext: "cobalt2026"
   - khoj admin password in plaintext: "cobalt123"
   - khoj admin email: a personal Gmail address
   This file must never be copied to OpenCobalt.

2. core/config.py line 80:
   NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "cobalt2026")
   The hardcoded default is a password. If config.py were copied without modification,
   the password would appear in the public repo. Must be stripped before any copy.

3. logs/ folder: 4,579 raw log files. These likely contain private session transcripts,
   personal prompts, agent outputs referencing private material. Never copy.

4. memory_store/: JSONL memory files. Contains personal notes and session memories.
   Never copy.

5. vault_index/: ChromaDB index of personal Obsidian vault.
   Never copy.

### MEDIUM

6. CLAUDE.md references phi3:latest as OBSERVER_MODEL. phi3 is not installed.
   Any config copied with phi3 reference will silently fail or mislead.

7. subsystems/agent-memory/.env and other .env files. Already gitignored in source
   but must be verified never to appear in OpenCobalt.

8. core/config.py also references COBALT_VAULT = ~/cobaltos-vault. If any OpenCobalt
   code defaulted to this path, it could read private vault notes. Must use a
   different, neutral default.

### LOW

9. Research logs in logs/performance, logs/courts, logs/router contain scoring data
   that could reveal private evaluation notes. Never copy.

10. prompts/ and _prompts/ folders: private prompt engineering notes. Some may
    reference sensitive personal context. Review before any partial extraction.

---

## 7. Stale Docs in ~/dev/AI

These files are stale or redirect-only. They should not become source of truth in OpenCobalt:

| File | Status |
|------|--------|
| TOOL_ROUTING.md (root) | Redirect stub pointing to ai/MASTER_CONTEXT.md |
| SECURITY_MODEL.md (root) | Redirect stub pointing to ai/AUTONOMY_POLICY.md |
| MASTER_CONTEXT.md (root) | Redirect stub pointing to ai/MASTER_CONTEXT.md |
| CLAUDE.md (root) | Compatibility entrypoint only, has stale phi3 reference |
| OPERATING_SYSTEM.md | Unclear status, not yet reviewed |
| ai/PROJECT_CONTEXT.md | Secondary/superseded by ai/MASTER_CONTEXT.md |
| ai/ARCHITECTURE.md | May be partially stale per DOCS_SOURCE_OF_TRUTH.md |
| ai/AI_WORKFLOW_MASTER.md | Listed as secondary in precedence order |
| ai/TESTING_STRATEGY.md | Listed as secondary in precedence order |

---

## 8. Docs That Should Become Source of Truth in OpenCobalt

These should be the canonical references going forward, written fresh for OpenCobalt:

| New File | Based On |
|----------|----------|
| docs/ARCHITECTURE.md | ai/MASTER_CONTEXT.md (rewrite for OpenCobalt scope) |
| docs/TOOL_ROUTING.md | ai/AUTONOMY_POLICY.md + routing doctrine |
| docs/DESIGN_SYSTEM.md | STITCH.md (adapted, renamed, OpenCobalt identity) |
| docs/MEMORY_SYSTEM.md | Original, describes SQLite spine |
| docs/ROADMAP.md | ai/ROADMAP.md (rewrite for OpenCobalt) |
| docs/REPO_AUDIT.md | This audit plus third-party repo classifications |

---

## 9. Other Dev Folders

Reviewed for relevance, will not be touched:

- ~/dev/on-pause/: BestFriends, claude-notary, cobalt-runtime, cobalt-studio,
  CobaltOS, indexing, MeridianCloud, metabolic-ops, StudyOS, Synapse, verdikt
  (multiple on-pause projects, not relevant to OpenCobalt)

- ~/dev/projects/: KYTH, lectRec, Noxe, Vectr, WeekOne
  (active/paused separate projects, not relevant)

- ~/dev/misc/: extensions, markdown-dump, misc-proj
  (miscellaneous, not relevant)

None of these should be touched, merged, or referenced in OpenCobalt.

---

## 10. Recommended Implementation Plan

Assuming user approves: proceed in this order.

### Phase 1: Git init + scaffold (no code yet)
- git init
- Create: README.md, QUICKSTART.md, pyproject.toml, .gitignore, .env.example,
  LICENSE, SECURITY.md, CREDITS.md, docs/, src/opencobalt/, tests/, examples/,
  assets/

### Phase 2: Core Python package
- Write fresh: src/opencobalt/core/models.py (Pydantic schemas)
- Write fresh: src/opencobalt/core/models_discovery.py (Ollama discovery, llama3/mistral only)
- Copy + adapt: automation/lib/events.py -> src/opencobalt/core/events.py
- Write fresh: src/opencobalt/core/ledger.py (SQLite via stdlib sqlite3)
- Write fresh: src/opencobalt/core/memory.py (reads/writes from ledger)
- Write fresh: src/opencobalt/core/context.py (context pack compiler)
- Copy + adapt: automation/lib/economic_router.py -> src/opencobalt/core/router.py
- Write fresh: src/opencobalt/core/verify.py
- Write fresh: src/opencobalt/core/public_safety.py

### Phase 3: CLI
- Write: src/opencobalt/cli.py (Typer)
- Commands: status, models, log, memory, context, route, verify, doctor, public-check, design

### Phase 4: Tests
- Write: tests/test_ledger.py, test_events.py, test_models_discovery.py,
  test_router.py, test_public_safety.py

### Phase 5: Docs
- Write: docs/ARCHITECTURE.md, TOOL_ROUTING.md, DESIGN_SYSTEM.md,
  DESIGNLAB.md, MEMORY_SYSTEM.md, ROADMAP.md, REPO_AUDIT.md,
  PORTFOLIO_SUMMARY.md, LOOM_DEMO_SCRIPT.md, EMPLOYER_README_NOTES.md,
  CREDITS.md, SECURITY.md

### Phase 6: UI scaffold
- Vite + React + TypeScript, only after Phase 1-5 are stable
- Design tokens from STITCH.md adapted for OpenCobalt

### Phase 7: Final audit
- docs/audits/001-public-readiness-audit.md

---

## 11. Stop Point

**STOP HERE.**

No implementation should begin until this audit is reviewed and approved.

Before proceeding to Phase 1, the user must confirm:

1. The public safety risks listed in Section 6 are understood. Especially:
   - NEXT_STEPS.md will never be copied
   - core/config.py NEO4J_PASSWORD default will be stripped before any copy
   - logs/, memory_store/, vault_index/ will never be copied

2. The candidate extraction list in Section 5 is approved or corrected.

3. The recommended implementation plan in Section 10 is approved or corrected.

4. There are no other private files, credentials, or personal data in ~/dev/AI
   that the audit may have missed. The user should manually verify any folders
   not inspected here before Phase 2 (code extraction) begins.

Once approved, implementation can begin with Phase 1.
