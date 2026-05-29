# Third-Party Repo Audit

All repos are located in `~/dev/git-repos`. None are vendored into OpenCobalt.

## Classification Key

- KEEP: Active optional integration path, worth documenting in CREDITS.md
- OPTIONAL: Could integrate later via adapter, low priority
- RESEARCH: Informed architecture, no planned integration
- DROP: Not aligned with current scope, remove from roadmap

---

## Repos

### instructor
- **Purpose:** Structured LLM outputs via Pydantic. Patches the OpenAI SDK to return typed objects.
- **Value to OpenCobalt:** High. If OpenCobalt adds API adapters, instructor would be the right way to get typed outputs from executive-tier models.
- **Maintenance burden:** Low. Actively maintained, pip-installable.
- **Classification:** KEEP (optional, future Phase 3)

### pydantic-ai
- **Purpose:** Pydantic's typed agent framework. Defines agents with typed inputs/outputs.
- **Value to OpenCobalt:** Medium. Useful if we add structured agent execution to the router.
- **Maintenance burden:** Low. pip-installable.
- **Classification:** KEEP (optional, future)

### mem0
- **Purpose:** Cross-session memory layer with semantic search.
- **Value to OpenCobalt:** Medium. The OpenCobalt memory spine is SQLite-based and simpler. mem0 is useful if vector search over memories is needed.
- **Maintenance burden:** Medium. Requires embedding model or API.
- **Classification:** OPTIONAL (future Phase 4+)

### dspy
- **Purpose:** Stanford programmatic LM framework. Defines pipelines of LM calls with optimization.
- **Value to OpenCobalt:** Low for now. Useful if routing itself is ever LM-driven.
- **Maintenance burden:** Medium.
- **Classification:** RESEARCH

### MoA-Ollama-Chat
- **Purpose:** Mixture-of-agents with local Ollama models. Multiple models debate and synthesize.
- **Value to OpenCobalt:** Medium. Interesting pattern for local-only multi-model synthesis.
- **Maintenance burden:** Low (simple codebase).
- **Classification:** RESEARCH

### Multi-Agents-Debate / llm-council
- **Purpose:** Adversarial multi-agent debate between LLM instances.
- **Value to OpenCobalt:** Research. Informed the adversarial ideation subsystem in Cobalt Forge.
- **Maintenance burden:** Low.
- **Classification:** RESEARCH

### GraphReasoning
- **Purpose:** Graph-based reasoning with LLMs.
- **Value to OpenCobalt:** Low for current scope.
- **Maintenance burden:** Medium.
- **Classification:** RESEARCH

### SciAgentsDiscovery
- **Purpose:** Multi-agent scientific discovery pipelines.
- **Value to OpenCobalt:** Low for current scope.
- **Maintenance burden:** Medium.
- **Classification:** RESEARCH

### self_improving_coding_agent (SICA)
- **Purpose:** Self-improving coding agent that iterates on its own outputs.
- **Value to OpenCobalt:** Research. Informed the self-improvement loop design in Cobalt Forge.
- **Maintenance burden:** Medium.
- **Classification:** RESEARCH

### storm
- **Purpose:** Long-form article synthesis via multi-agent collaboration.
- **Value to OpenCobalt:** Low for current scope.
- **Maintenance burden:** Medium.
- **Classification:** RESEARCH

### gepa
- **Purpose:** Genetic evolutionary prompt adaptation.
- **Value to OpenCobalt:** Low.
- **Maintenance burden:** Medium.
- **Classification:** RESEARCH

### mapper-mo
- **Purpose:** Mapping and reasoning patterns.
- **Value to OpenCobalt:** Low.
- **Maintenance burden:** Unknown.
- **Classification:** DROP

### AI-Scientist
- **Purpose:** Autonomous hypothesis-to-paper research agent. Heavy infra (LaTeX, datasets).
- **Value to OpenCobalt:** None currently.
- **Maintenance burden:** High.
- **Classification:** DROP

### crewAI
- **Purpose:** Multi-agent orchestration with role definitions and task delegation.
- **Value to OpenCobalt:** Low. OpenCobalt routes to tools, it does not orchestrate agents.
- **Maintenance burden:** High (large framework).
- **Classification:** DROP

### llama_index
- **Purpose:** Retrieval and indexing over large document sets.
- **Value to OpenCobalt:** Low for current scope. Context compiler handles simpler use case.
- **Maintenance burden:** Medium.
- **Classification:** OPTIONAL (if context compiler needs vector search)

### graphrag
- **Purpose:** Graph-based RAG using entity extraction and knowledge graphs.
- **Value to OpenCobalt:** Low.
- **Maintenance burden:** High.
- **Classification:** DROP

### gpt-researcher
- **Purpose:** Autonomous web research agent.
- **Value to OpenCobalt:** None. Web research is out of scope.
- **Maintenance burden:** Medium.
- **Classification:** DROP

### agentops
- **Purpose:** Agent observability and tracing.
- **Value to OpenCobalt:** Low. OpenCobalt's ledger serves this purpose locally.
- **Maintenance burden:** Low.
- **Classification:** OPTIONAL (future, if hosted observability wanted)

### khoj
- **Purpose:** Local search over Obsidian and documents. Requires PostgreSQL + pgvector.
- **Value to OpenCobalt:** Low. Too heavy for the current scope.
- **Maintenance burden:** Very high (PostgreSQL dependency).
- **Classification:** DROP

### SWE-agent
- **Purpose:** Automated software engineering benchmark agent.
- **Value to OpenCobalt:** None. Benchmark tooling, not orchestration infrastructure.
- **Maintenance burden:** High.
- **Classification:** DROP

### txtai
- **Purpose:** Search and embedding platform.
- **Value to OpenCobalt:** Low.
- **Maintenance burden:** Medium.
- **Classification:** DROP

### openevolve
- **Purpose:** Code evolution via population-based search.
- **Value to OpenCobalt:** None currently.
- **Maintenance burden:** Unknown.
- **Classification:** DROP

### e2b
- **Purpose:** Cloud code execution sandboxes.
- **Value to OpenCobalt:** Low. OpenCobalt is local-first.
- **Maintenance burden:** Low (API-based).
- **Classification:** OPTIONAL (very future)

### autogen
- **Purpose:** Multi-agent conversation framework from Microsoft.
- **Value to OpenCobalt:** Low. Large framework with significant dependency footprint.
- **Maintenance burden:** High.
- **Classification:** DROP

### ADAS
- **Purpose:** Automotive domain (unrelated to OpenCobalt).
- **Value to OpenCobalt:** None.
- **Classification:** DROP

## Summary

| Classification | Count | Repos |
|----------------|-------|-------|
| KEEP | 2 | instructor, pydantic-ai |
| OPTIONAL | 4 | mem0, llama_index, agentops, e2b |
| RESEARCH | 7 | dspy, MoA-Ollama-Chat, Multi-Agents-Debate/llm-council, GraphReasoning, SciAgentsDiscovery, SICA, storm, gepa |
| DROP | 11 | mapper-mo, AI-Scientist, crewAI, graphrag, gpt-researcher, khoj, SWE-agent, txtai, openevolve, autogen, ADAS |
