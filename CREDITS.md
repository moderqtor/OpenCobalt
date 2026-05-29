# Credits

## Runtime dependencies

- [Typer](https://typer.tiangolo.com/) -- CLI framework
- [Pydantic v2](https://docs.pydantic.dev/) -- data validation and schema definitions
- [Rich](https://rich.readthedocs.io/) -- terminal output formatting
- Python standard library sqlite3 -- ledger persistence

## Inspired by or optionally integrable with

These projects are not vendored into OpenCobalt. They informed the architecture or may be integrated via optional adapters in future phases.

**Local models:**
- [Ollama](https://ollama.ai/) -- local model serving

**Memory and retrieval:**
- [mem0](https://github.com/mem0ai/mem0) -- cross-session memory layer patterns
- [ChromaDB](https://www.trychroma.com/) -- vector store (used in private Cobalt Forge, not included here)
- [Qdrant](https://qdrant.tech/) -- vector store alternative
- [txtai](https://neuml.github.io/txtai/) -- search and embeddings

**Structured outputs:**
- [instructor](https://github.com/jxnl/instructor) -- structured LLM outputs via Pydantic
- [DSPy](https://github.com/stanfordnlp/dspy) -- Stanford programmatic LM / prompt optimization
- [pydantic-ai](https://ai.pydantic.dev/) -- typed agent framework

**Multi-agent patterns:**
- [crewAI](https://github.com/crewAIInc/crewAI) -- multi-agent orchestration framework
- [MoA-Ollama-Chat](https://github.com/InsightEdgeAI/MoA-Ollama-Chat) -- mixture-of-agents with local Ollama models
- [Multi-Agents-Debate](https://github.com/Skytliang/Multi-Agents-Debate) -- adversarial multi-agent debate
- [llm-council](https://github.com/theyorubayesian/llm-council) -- LLM council / multi-model consensus

**Research and synthesis:**
- [STORM](https://github.com/stanford-oval/storm) -- long-form synthesis agent
- [SciAgentsDiscovery](https://github.com/lamm-mit/SciAgentsDiscovery) -- scientific multi-agent orchestration
- [GraphReasoning](https://github.com/lamm-mit/GraphReasoning) -- graph-based reasoning patterns
- [gpt-researcher](https://github.com/assafelovic/gpt-researcher) -- autonomous research agent
- [AI-Scientist](https://github.com/SakanaAI/AI-Scientist) -- autonomous hypothesis-to-paper loop

**Self-improvement and evolution:**
- [SICA / self_improving_coding_agent](https://github.com/wysoczanska/self_improving_coding_agent) -- self-improving coding agent patterns
- [GEPA](https://github.com/xianglinyang/gepa) -- genetic evolutionary prompt adaptation
- [OpenEvolve](https://github.com/codelion/optillm) -- code evolution patterns

**Agent infrastructure:**
- [agentops](https://github.com/AgentOps-AI/agentops) -- agent observability
- [e2b](https://e2b.dev/) -- cloud code execution sandboxes
- [SWE-agent](https://github.com/princeton-nlp/SWE-agent) -- automated software engineering

**Developer tools that OpenCobalt routes to:**
- [Claude Code](https://claude.ai/claude-code) -- Anthropic's CLI for Claude
- [Codex CLI](https://github.com/openai/codex) -- OpenAI's CLI coding agent
- [Gemini CLI](https://github.com/google-gemini/gemini-cli) -- Google's CLI for Gemini
- [Cursor](https://cursor.sh/) -- AI-native code editor

**Knowledge tools:**
- [Obsidian](https://obsidian.md/) -- local markdown knowledge base (vault export target, not source)
- [khoj](https://github.com/khoj-ai/khoj) -- local search over Obsidian + docs
- [llama-index](https://github.com/run-llama/llama_index) -- retrieval and indexing
- [graphrag](https://github.com/microsoft/graphrag) -- graph-based RAG
