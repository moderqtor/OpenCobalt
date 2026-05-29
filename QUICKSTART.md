# Quickstart

Get from clone to first useful output in under two minutes.

Requires Python 3.11+.

## 1. Install

```bash
git clone https://github.com/moderqtor/OpenCobalt
cd OpenCobalt
pip install -e ".[dev]"
```

## 2. First run

```bash
opencobalt status
```

Shows: Python version, repo path, Ollama availability, ledger row counts, docs presence, and a public safety scan. A healthy system prints all green with a health bar at the bottom (`11/11 healthy`). If Ollama is not installed, those rows show as unavailable -- the rest of the system still works.

## 3. Route a task

```bash
opencobalt route "design the event spine architecture"
opencobalt route "summarize this log file"
```

Each command prints a score table across all five tools (claude-code, codex-cli, gemini-cli, cursor, ollama), the recommended tool, matched keywords, and the runner-up.

- Architecture, security, and public-facing tasks route to executive-tier tools (claude-code, gemini-cli).
- Summarization, tagging, and extraction route to the worker tier (ollama, local only).
- Refactoring with tests routes to the manager tier (codex-cli, cursor).

Route decisions are logged to the ledger by default.

## 4. Build a context pack

```bash
opencobalt context
```

Compiles README, docs, and src files into a single markdown file at `.opencobalt/context/latest.md`. The output shows the file count and a token estimate. Feed this file to any agent as a project briefing.

## 5. Run verification

```bash
opencobalt verify
```

Runs pytest and the public safety scanner. Records pass/fail results in the ledger. Fails loudly if any test fails or any safety issue is detected.

## 6. Benchmark the router

```bash
opencobalt benchmark
```

Routes 10 representative tasks and prints a tier breakdown table. Use this to confirm the router is classifying tasks as expected after any config change.

## 7. Optional: Ollama (local model agents)

Install from [ollama.ai](https://ollama.ai), then:

```bash
ollama pull llama3
```

With Ollama running, `opencobalt models` lists available local models. The summarizer and tagger agents call Ollama directly for worker-tier tasks.

## 8. Optional: UI dashboard shell

```bash
cd ui && npm install && npm run dev
```

Opens at `localhost:5173`. The React + Tailwind shell is a frontend scaffold -- the backend API is not yet wired.

## What's next

- Full command reference: `README.md`
- Architecture and design decisions: `docs/`
- Agent, skill, and integration examples: `examples/`
- Live terminal dashboard: `opencobalt tui`
- Full health check: `opencobalt doctor`
- Ledger analytics: `opencobalt stats`
- Store notes: `opencobalt memory add "your note" --namespace project`
- Config: `opencobalt config set api_enabled true`
