# OpenCobalt

**Local-first AI orchestration and memory control plane.**

OpenCobalt routes work across coding agents, local models, session logs, project context, and verification workflows. It is not a chatbot. It is not a generic AI assistant wrapper. It is a control plane that coordinates AI tools you already use.

---

## What It Does

- Routes tasks to the right tool (Claude Code, Codex CLI, Gemini CLI, Cursor, Ollama) based on task type, risk level, and tier
- Maintains a durable SQLite ledger of sessions, tool runs, route decisions, and verification results
- Compiles context packs from project docs and source files for agent consumption
- Scans for public-safety issues before any push: secrets, private paths, oversized artifacts
- Runs verification pipelines and records results

---

## Architecture

```mermaid
graph TD
    CLI["opencobalt CLI"] --> Router["Router\ndeterministic, keyword-based"]
    CLI --> Ledger["SQLite Ledger\nsource of truth"]
    CLI --> Context["Context Compiler\ndocs + src -> context pack"]
    CLI --> Safety["Public Safety Scanner\npre-push hygiene"]
    CLI --> Verify["Verification Runner\npytest + public-check"]
    CLI --> Memory["Memory Store\nrecords via ledger"]

    Router --> |"executive tier"| Executive["Claude Code\nCodex CLI\nGemini CLI"]
    Router --> |"worker tier"| Worker["Ollama\nllama3, mistral\nlocal only"]
    Router --> |"manager tier"| Manager["Cursor\nCodex CLI"]

    Ledger --> Export["Markdown Export\n.opencobalt/exports/"]
```

Ollama models are **worker-tier only**: summarization, tagging, extraction, rough drafts. Serious decisions (architecture, security, public docs) route to executive-tier tools only.

---

## Install

```bash
git clone https://github.com/moderqtor/OpenCobalt
cd OpenCobalt
pip install -e ".[dev]"
```

Requires Python 3.11+. Ollama is optional (local model commands degrade gracefully without it).

---

## CLI

```bash
# System status: Python, Ollama, ledger, docs, safety scan
opencobalt status

# List installed Ollama models
opencobalt models

# Route a task to the right tool
opencobalt route "design the event spine architecture"
opencobalt route "summarize this log file"

# Write a session event to the ledger
opencobalt log --summary "reviewed auth module"

# Memory
opencobalt memory status
opencobalt memory export --project opencobalt

# Build a context pack from docs + src
opencobalt context

# Run tests + public safety scan, record results
opencobalt verify

# Pre-push hygiene scan
opencobalt public-check

# Full health check
opencobalt doctor
```

---

## What Works Today

- CLI with all commands above
- Deterministic task router (keyword-based, no LLM calls)
- SQLite ledger: events, verification results, route decisions, memory records
- Ollama model discovery with graceful fallback
- Context pack compiler
- Public safety scanner: .env detection, secret patterns, oversized files, private vault paths
- 58 passing tests

---

## What Is Experimental

- Cost control module (stub -- not yet wired to API adapters)
- DesignLab / Visual Compiler (documented, not yet implemented)
- UI layer (planned -- see docs/DESIGN_SYSTEM.md and docs/DESIGNLAB.md)
- Obsidian markdown export mirror (schema exists, Obsidian write path not wired)

---

## Limitations

- No API calls by default. All routing is deterministic and local.
- Optional API adapters (Anthropic, OpenAI, Google) require explicit configuration in `.env`.
- Ollama must be running separately for local model commands. OpenCobalt does not launch Ollama.
- The router is keyword-based. It does not infer task semantics.
- No persistent agent execution. OpenCobalt routes and logs -- it does not run agents autonomously.

---

## Screenshot

![OpenCobalt status command](assets/readme/status-placeholder.png)

*(screenshot placeholder -- run `opencobalt status` to see the live output)*

---

## Credits

See [CREDITS.md](CREDITS.md) for libraries and research projects that informed this work.

---

## License

MIT. See [LICENSE](LICENSE).
