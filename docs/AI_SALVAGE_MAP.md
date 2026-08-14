# Old `moderqtor/AI` salvage map

Planning only. Do not merge or copy `moderqtor/AI` into OpenCobalt.

Inspected remotely from https://github.com/moderqtor/AI (README and tree, 2026-08-13).
This cloud workspace does not contain `~/dev/AI`. Nothing was cloned or imported.

OpenCobalt already owns durable SQLite state, ExecutionEngine, capability routing,
Missions, receipts, approvals, and staged coding. The old repo is a local-first
control-plane / cognitive-OS prototype with CrewAI, ChromaDB, Neo4j stubs, khoj,
and launchd daemons. Those stacks stay archived unless a later mission proves a
specific gap SQLite and the current control loop cannot cover.

| Area | Problem it solved | OpenCobalt already? | Concept worth keeping? | Code worth keeping? | Dependencies | Security | Decision |
|---|---|---|---|---|---|---|---|
| Economic / outcome-aware router | Score routes from cost, latency, failure, preference | Heuristic router plus bounded success/latency/cancellation hooks (this branch) | Yes: empirical calibration over declared priors | Unlikely; old scoring is a different product | Unknown local history stores | Low if read-only | Concept-only |
| Agent inventory | Standing CrewAI roles and workflow templates | Provider registry, capability roles, builtin prompt contracts | Inventory of *capabilities*, not named crew personas | No | crewAI, LiteLLM, optional OpenAI | External LLM if keys set | Already superseded as architecture; archive crew code |
| Evaluator / eval court | Adversarial review of worker output | Verification records, receipts, opportunity/evolve loops | Independent verification as a first-class phase | Maybe later, not now | Forge Makefile / court runners | Medium if it can mutate | Concept-only |
| Plugin permissions / gateway | Bound what plugins may do | ExecutionEngine, autonomy envelopes, skill import security, Chat answer-only | Explicit permission classes | Review later if a plugin surface is needed | Forge plugin gateway | High | Concept-only; do not import a second gateway |
| Knowledge / context retrieval | Vault + Chroma search, memory JSONL | Research retrieval (PubMed, DOI, gov HTTPS, attachments), SQLite memory, local-only | Retrieval as data, not authority | No Chroma/Neo4j/khoj | ChromaDB, Neo4j stub, khoj/Postgres, Obsidian vault paths | Vault paths and API keys | Already superseded for product retrieval; archive vector-db stack |
| Goal compiler | Turn a task string into a governed plan | Missions, auto orchestrator (plan-only), mission extractor | Compile goals into capability-bounded steps | Unlikely wholesale | Forge `goal_compiler` | Medium | Concept-only; extend Mission steps instead |
| Self-improvement health scanner | Cold-boot status of local services | `public-check`, provider health, `opencobalt` status surfaces | Honest readiness vs installed-but-unusable | No launchd/daemon copy | launchd, Ollama, port 7777 | Low | Already superseded for OpenCobalt; archive daemons |

Hard archive (do not port):

- CrewAI crews and role backstories
- Neo4j ontology stubs
- ChromaDB vault index as a second knowledge plane
- khoj / PostgreSQL
- launchd memory/ideation daemons
- Obsidian vault path coupling (historical local vault layout)
- Any second durable state besides SQLite

If a later pass needs more than this table, inspect `automation/lib/` and
`ai/DECISIONS.md` in the old repo in place. Do not vendor the tree.
