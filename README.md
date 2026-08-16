# OpenCobalt

[![CI](https://github.com/moderqtor/OpenCobalt/actions/workflows/ci.yml/badge.svg)](https://github.com/moderqtor/OpenCobalt/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

OpenCobalt is a personal autonomous intelligence fabric.

The user provides intent, not workflow. OpenCobalt translates sparse or
detailed human intent into an adaptive program of work across available
intelligence, agents, tools, applications, runtimes, and compute.

## North Star

OpenCobalt compiles human intent into an adaptive `WorkGraph` of reasoning,
ideation, criticism, experiments, implementation, verification, and revision.
It coordinates heterogeneous systems (Codex, Claude, Gemini, Antigravity,
Cursor, Stitch, GitHub, Vercel, browsers, local models) while maintaining
durable state, receipts, and authority boundaries across provider sessions.

The primary user interaction is simple:

```
Tell OpenCobalt what you want.
```

The complexity belongs behind that interaction.

## What works today

The local web workspace and CLI are the operational surfaces:

```bash
opencobalt ui
```

That starts a FastAPI backend on `localhost:8000` and a React workspace on
`localhost:5173`. Chat is the default page. Give OpenCobalt a goal; it records
the conversation, routes work through capability adapters, and keeps state in local SQLite.

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
| Autonomous Creation v0 | Under active implementation (IntentContract + WorkGraph + supervisor) |
| Tauri desktop wrapper | Usable via `opencobalt desktop` if Cargo/Tauri tooling is installed. The web UI is canonical. |

Claude Code and Codex are real execution adapters, but ordinary Chat currently
fails closed for them until an answer-only isolation boundary exists. Gemini
CLI is discovery-only. Mock is a development provider.

Citation linkage checks that a claim points at retrieved mission evidence. It
does not prove the claim is true. Coding staging contains writes to a staged
workspace; it is not OS-level sandboxing.

## Distinctive pieces

- **Intent Compilation**: Requests compile into structured `IntentContract` records distinguishing hard constraints from inferred creative dimensions.
- **WorkGraph Representation**: Work nodes represent what needs to become true, not vendor calls.
- **Capability Roles**: Capabilities precede vendor names: cheap local reasoning, fast general reasoning, strong reasoning, research, coding analysis, coding execution.
- **Durable Missions**: Missions persist independently of any provider session.
- **Staging & Containment**: Coding-agent work produces a ChangeSet requiring explicit promotion into the authoritative repository.
- **Interchangeable Providers**: OpenCobalt owns state, routing, policy, and receipts.

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
2. Write what you want. Automatic routing is on unless you choose Manual.
3. Open Controls only for persona, approach, privacy, local-only, a
   manual provider, or an optional repository path. Those draft choices
   apply to the first send. A repository can be attached before any
   message; the path is stored with the conversation when it is created.
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
  operator, telemetry) that are real but are supporting substrate.

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
