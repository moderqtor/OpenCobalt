# OpenCobalt

[![CI](https://github.com/moderqtor/OpenCobalt/actions/workflows/ci.yml/badge.svg)](https://github.com/moderqtor/OpenCobalt/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

OpenCobalt is a personal control layer for allocating intelligence and
capability.

AI work is currently split across models, local runtimes, cloud runtimes,
coding agents, research tools, skills, context, and memory. People usually
make those orchestration decisions by hand. OpenCobalt takes a goal and handles
routing, context, memory, research, coding execution policy, approvals, and
durable state behind a simple surface.

It is inspectable, not magical. Route scores, provider evidence, Missions,
approvals, and receipts stay visible when you want them. It is not a generic
chatbot, not a thin API wrapper, and not a coding-only or research-only app.

## What works today

The local web workspace is the primary surface:

```bash
opencobalt ui
```

That starts a FastAPI backend on `localhost:8000` and a React workspace on
`localhost:5173`. Chat is the default page. Give OpenCobalt a goal; it records
the conversation, selects a route, and keeps the result in local SQLite.

| Capability | Status |
|---|---|
| Durable Chat, conversations, and personas | Implemented |
| Inspectable capability routing | Implemented. Scores are heuristics, not probabilities. |
| Ollama and Antigravity Chat execution | Implemented when local discovery proves the bounded invocation |
| Research Missions with retrieved sources, evidence, and citation linkage | Implemented. HTML, PDF, PubMed, DOI/Crossref, government hosts, and user uploads. |
| Document attachments on Chat and Research | Implemented for PDF, Markdown, plain text, HTML, and CSV. Uploads are data, not instructions. |
| Coding analysis and Cursor ACP coding Missions | Implemented. Mutations stay staged until explicit promotion. |
| Memory, Skills, Ledger, Providers, Settings | Implemented |
| Local-only request constraint | Implemented |
| Approvals for provider tool use and coding promotion | Implemented |
| CLI routing, receipts, missions, and `auto` planning | Implemented |
| Tauri desktop wrapper | Usable via `opencobalt desktop` if Cargo/Tauri tooling is installed. The web UI is canonical. |

Claude Code and Codex are real execution adapters, but ordinary Chat currently
fails closed for them until an answer-only isolation boundary exists. Gemini
CLI is discovery-only. Mock is a development provider.

Citation linkage checks that a claim points at retrieved mission evidence. It
does not prove the claim is true. Coding staging contains writes to a staged
workspace; it is not OS-level sandboxing.

## Distinctive pieces

- Capability roles come before vendor names: cheap local reasoning, fast
  general reasoning, strong reasoning, research, coding analysis, coding
  execution.
- Personas are interaction policies, not provider replicas.
- Missions persist independently of any provider session.
- Research retrieves public HTTPS sources, user documents, and stores evidence locally.
- Coding-agent work produces a ChangeSet and requires explicit promotion into
  the authoritative repository.
- Providers are interchangeable. OpenCobalt owns state, routing, policy, and
  receipts.

## Install and start

Python 3.11+ and Node.js/npm are required. From a checkout:

```bash
git clone https://github.com/moderqtor/OpenCobalt
cd OpenCobalt
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev,server]"
opencobalt ui
```

Start from the repository root so the UI and CLI share `.opencobalt/ledger.db`.
Starting the workspace and inspecting local records does not call a provider.
Sending a request through a cloud CLI uses that CLI's own auth and network.

Ollama is optional. If a local loopback model is available, OpenCobalt can use
it for local-only Chat and some research roles.

## First use

1. Open Chat and start typing, or click New.
2. Write the goal. Automatic routing is on unless you choose Manual.
3. Open Controls only for persona, approach, privacy, local-only, a
   manual provider, or an optional repository path.
4. Open Details on a response, or Missions, when you want the decision
   record. Routes, Ledger, Skills, Providers, and Settings stay under
   System.

Research starts when the cognitive policy is Research or Research synthesis.
Coding-agent work starts when Chat can classify a mutating repo task and a
project path is attached.

## Project status and limits

OpenCobalt is an active local project, not a hosted product.

- Real CLI providers complete a one-shot command; this is not native token
  streaming.
- Cancellation is cooperative and does not guarantee killing an already-running
  provider process.
- Chat has no approval-and-resume cycle for tools. `always_ask` blocks model
  execution rather than pausing it.
- Research source acquisition is bounded public HTTPS retrieval, not a
  commercial deep-research crawler.
- Desktop packaging still requires development tooling.
- The CLI has additional subsystems (opportunity engine, evolve, daily
  operator, telemetry) that are real but are not the primary product story.

## Documentation

- [Doctrine](OPENCOBALT.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Workspace](docs/PERSONAL_AI_ROUTER.md)
- [Routing](docs/routing.md)
- [Research](docs/research.md)
- [Coding](docs/coding.md)
- [Roadmap](docs/ROADMAP.md)
- [Security](SECURITY.md)
- [Docs index](docs/README.md)

## License

MIT. See [LICENSE](LICENSE).
