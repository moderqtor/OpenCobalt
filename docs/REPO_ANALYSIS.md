# Repo Analysis

External repositories at `~/dev/git-repos/` evaluated for integration into OpenCobalt.

All licensing notes below refer to distribution impact for OpenCobalt's MIT license.
AGPL-3.0 repos (mem0, Khoj) must be treated as local sidecars -- never linked into the
main package or distributed as a dependency.

---

## mem0

**What it does:** Memory layer for AI agents. Stores, searches, and retrieves memories
across sessions. Supports semantic search via pluggable vector backends.

**How it slots in:** Layer 2 agent memory. MemoryBridge in `memory_bridge.py` provides
the interface; mem0 can back it if configured. Currently mem0 requires an LLM and a
vector store (no SQLite vector support), so the default implementation uses SQLite
text search.

**Integration tier:** TIER2 -- integrate when semantic search is needed and a vector
store is acceptable. For now, the SQLite path is sufficient.

**License:** Apache 2.0. No distribution restrictions for OpenCobalt.

**Effort:** Medium. Wiring mem0 requires a vector store choice (Chroma local or Qdrant)
and an embedder (local model or API). SQLite path is already implemented.

---

## agentops

**What it does:** Cloud-based agent observability platform. Tracks sessions, tool calls,
cost, latency, and errors. Provides a hosted dashboard.

**How it slots in:** Observability layer. `observability.py` in OpenCobalt provides the
same interface backed by SQLite. If agentops local mode becomes available, it could
replace the SQLite backend for richer telemetry.

**Integration tier:** TIER3 -- study only. Requires cloud API key and dashboard account.
Not compatible with local-first constraint without forking.

**License:** MIT. No distribution restrictions.

**Effort:** Low to wire if cloud is acceptable; the current SQLite implementation
already covers the required interface.

---

## crewAI

**What it does:** Multi-agent orchestration framework. Defines agents with roles and
goals, assigns tasks, coordinates output handoffs between agents.

**How it slots in:** Could power a multi-agent pipeline where OpenCobalt's router
dispatches to a CrewAI crew for complex tasks. More overhead than the current
agent registry for single-agent tasks.

**Integration tier:** TIER2 -- consider when multi-agent pipelines are needed (e.g.,
research + summarize + review as a chained crew).

**License:** MIT. No distribution restrictions.

**Effort:** Medium. CrewAI is opinionated about agent structure; integrating would
require wrapping OpenCobalt agents as CrewAI `Agent` objects.

---

## pydantic-ai

**What it does:** GenAI agent framework from the Pydantic team. Uses Pydantic models
for structured agent inputs/outputs. Supports multiple LLM backends with type safety.

**How it slots in:** Could replace or augment the current BaseAgent ABC with a typed,
validated agent interface. Particularly useful for the router: replacing keyword
scoring with a structured pydantic-ai agent that returns typed RouteDecision objects.

**Integration tier:** TIER1 -- high value for router upgrade. Pydantic is already a
dependency; pydantic-ai extends it naturally. The bandit router (adaptive routing
based on benchmark history) is a good first use case.

**License:** MIT. No distribution restrictions.

**Effort:** Low. Pydantic is already in the stack; pydantic-ai adds one new dependency.

---

## instructor

**What it does:** Structured LLM outputs via Pydantic validation. Wraps OpenAI/Anthropic
clients to enforce JSON schema on completions. Handles retries and validation errors.

**How it slots in:** Useful when OpenCobalt makes API calls (when api_enabled is true)
and needs structured output from LLMs. For example, extracting RouteDecision objects
from a language model response.

**Integration tier:** TIER2 -- integrate when API adapters are wired. Not needed until
the optional API layer is built.

**License:** MIT. No distribution restrictions.

**Effort:** Low. Drop-in wrapper on top of existing API client calls.

---

## llama_index

**What it does:** Framework for building agentic applications over documents. Ingestion
pipelines, RAG (retrieval-augmented generation), document agents.

**How it slots in:** Context pack compiler upgrade. The current `context.py` does a
simple file scan and size cap. LlamaIndex would add semantic chunking, reranking, and
multi-document retrieval for richer context packs.

**Integration tier:** TIER2 -- integrate when the context compiler needs semantic
retrieval. Currently the simple approach is sufficient.

**License:** MIT. No distribution restrictions.

**Effort:** High. LlamaIndex is a large framework; integrating requires storage backend
choices and a significant surface area to maintain.

---

## e2b

**What it does:** Cloud-hosted sandboxed code execution environments. Runs code safely
in isolated containers accessed via an API.

**How it slots in:** Safe code execution for the verification pipeline. When
`opencobalt verify` runs tests, it could run them in an e2b sandbox for stronger
isolation. Useful for executing untrusted agent-generated code.

**Integration tier:** TIER3 -- study only. Requires cloud account and network access.
Not compatible with the local-first default.

**License:** Apache 2.0. No distribution restrictions.

**Effort:** Low to integrate the SDK; but the cloud dependency disqualifies it from
the default path.

---

## SWE-agent

**What it does:** Autonomous software engineering agent. Operates on a GitHub
repository to resolve issues by browsing code, writing patches, and running tests.
(Note: most active development has moved to mini-swe-agent.)

**How it slots in:** Model for the full-loop agent execution design. OpenCobalt routes
tasks but does not execute them; SWE-agent shows how to close the loop with actual
code changes, test runs, and PR creation.

**Integration tier:** TIER3 -- study only. Useful reference for designing OpenCobalt's
eventual full-loop execution mode.

**License:** MIT. No distribution restrictions.

**Effort:** High. SWE-agent is a complete agent with its own execution environment;
importing pieces selectively is non-trivial.

---

## self_improving_coding_agent

**What it does:** A coding agent that runs an improvement loop on its own codebase:
benchmark, archive results, run agent on itself, repeat. Demonstrates iterative
self-improvement via benchmark-driven selection.

**How it slots in:** Direct inspiration for OpenCobalt's self-improvement loop design.
The benchmark store and leaderboard in OpenCobalt are already built with this pattern
in mind. The loop design (evaluate, store, improve, repeat) maps directly to
`opencobalt benchmark` + agent execution.

**Integration tier:** TIER3 -- study only. The pattern is more important than the code.

**License:** MIT. No distribution restrictions.

**Effort:** N/A -- reference only.

---

## dspy

**What it does:** Declarative Self-improving Python. Programs LLMs compositionally
using modules (not raw prompts). Includes automatic prompt optimization algorithms
(BootstrapFewShot, MIPRO, etc.).

**How it slots in:** Bandit router upgrade. The current router is deterministic
keyword-based. DSPy could power an adaptive router that optimizes its routing
decisions based on benchmark history (treating routing as a classification module
that can be compiled and optimized).

**Integration tier:** TIER2 -- integrate when building the adaptive router. DSPy
would replace static keyword profiles with a learned routing function.

**License:** MIT. No distribution restrictions.

**Effort:** Medium. DSPy has a learning curve; integrating requires defining the
routing task as a DSPy program and setting up a training set from benchmark records.

---

## graphrag

**What it does:** Microsoft's graph-based RAG system. Builds a knowledge graph from
a corpus of documents and answers questions by traversing the graph rather than doing
flat vector search.

**How it slots in:** Layer 3 project knowledge upgrade. Khoj does flat semantic search;
GraphRAG would provide graph-structured retrieval of architecture decisions and their
relationships (e.g., "what decisions depended on choosing SQLite?").

**Integration tier:** TIER2 -- integrate as an alternative to Khoj for project
knowledge retrieval when graph-structured queries are needed.

**License:** MIT. No distribution restrictions.

**Effort:** High. GraphRAG requires an indexing pipeline, a graph store, and an LLM
for entity extraction. Significant setup and operational overhead.

---

## txtai

**What it does:** All-in-one AI framework with pipelines for embeddings, semantic
search, classification, and RAG. Supports local SQLite + Faiss for vector storage.

**How it slots in:** Strong candidate for MemoryBridge vector search. txtai supports
SQLite-backed vector indexes (via sqlite-vec), which would allow semantic search on
agent memories without requiring Qdrant or Chroma.

**Integration tier:** TIER1 -- evaluate for MemoryBridge semantic search. txtai's
local SQLite vector support is the closest match to OpenCobalt's architecture
constraints. Would replace the current LIKE-based text search with proper embeddings.

**License:** Apache 2.0. No distribution restrictions.

**Effort:** Low to medium. txtai supports local-only operation with no cloud services.
Adding an embedder (e.g., a local sentence-transformers model) is the main overhead.

---

## Prioritized integration roadmap

### Current phase (build now)

**pydantic-ai** (TIER1): Use for the API adapter layer and structured agent outputs
when `api_enabled` is true. Already in the dependency graph (Pydantic); minimal
addition.

**txtai** (TIER1): Evaluate for MemoryBridge semantic search upgrade. Local SQLite
vector support matches architecture constraints.

### Bandit router phase (Phase 4-5)

**dspy**: Replace static keyword profiles with a learned routing function backed by
benchmark data. Implement as an optional module that activates when benchmark data
exceeds a threshold.

**pydantic-ai**: Already recommended above; also useful here for structured routing
decision types.

### Context and RAG upgrade phase

**llama_index**: Upgrade context pack compiler with semantic chunking and reranking.
Use when simple file scans are no longer sufficient.

**graphrag**: Add graph-structured project knowledge retrieval as an alternative to
Khoj for complex architectural queries.

**txtai**: Already recommended above; also the natural choice for local RAG.

### Self-improvement loop design (study phase)

**self_improving_coding_agent**: Reference implementation for the benchmark-driven
improvement loop. Study the evaluate-archive-improve cycle before implementing.

**SWE-agent / mini-swe-agent**: Reference for closing the loop between routing and
actual code execution. Study before building full-loop agent execution in OpenCobalt.
