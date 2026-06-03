# Portfolio Summary

## Resume Bullets

- Built OpenCobalt, a local-first AI orchestration CLI in Python that routes tasks across Claude Code, Codex CLI, Gemini CLI, Cursor, and Ollama using a deterministic scoring router with tiered model classification and a SQLite session ledger
- Implemented persistent agent memory with SQLite-backed MemoryBridge, session observability tracking, agent benchmarking with composite scoring, and repo-hygiene public-check tooling; 244 tests, ruff lint clean, GitHub Actions CI

---

## What This Is

OpenCobalt is a local-first AI orchestration and memory control plane. It routes work across coding agents, local models, session logs, project context, and verification workflows.

It was built to solve a real problem: when you use five different AI tools across a day of development work, you have no memory of what happened, no log of what each tool produced, no consistent way to decide which tool to use for which task, and no pre-push hygiene pass to catch mistakes.

OpenCobalt provides a minimal, working answer to each of those problems.

## What Demonstrates Technical Skill

### Systems design
- A real schema (SQLite, Pydantic v2) for session events, tool runs, route decisions, verification results, and memory records
- Append-only event spine pattern
- Clean separation between source of truth (SQLite), generated mirrors (markdown), and runtime artifacts (context packs)

### Software engineering
- 244 passing tests covering models, ledger, events, memory, router, public safety scanner, cost module, agents, skills, and integrations
- No test mocking of core logic -- tests use real temp SQLite databases
- Clean module design: each file has one responsibility, one public interface
- CI workflow running on ubuntu-latest via GitHub Actions

### AI-native development patterns
- Deterministic routing (keyword scoring) that explicitly separates worker-tier from executive-tier tools
- Ollama model discovery that degrades gracefully instead of crashing
- Public safety scanner that catches real classes of pre-push mistakes
- Cost control module with per-run and monthly budget caps
- Subagent and skill library system (BaseAgent ABC + 4 concrete agents, BaseSkill ABC + 3 skills)
- External integration registry with 6 integrations (aider, ollama, claude-code, gemini-cli, cursor, context7)
- Live React dashboard with FastAPI backend, starts with `opencobalt ui`

### Applied analytics mindset
- Routing decisions are scored, not binary
- Route tier classification maps to risk and cost tradeoffs
- Ledger schema is designed for future aggregation and analysis

## What This Is Not

- Not a production service
- Not an autonomous agent that runs without human oversight
- Not a demonstration of every possible AI pattern
- Not a generic chatbot wrapper

## Skills Demonstrated

- Python (3.11+, Pydantic v2, Typer, Rich, sqlite3)
- SQLite schema design
- CLI design
- Test design (pytest, 244 tests)
- AI tool orchestration patterns (routing tiers, cost awareness, agent/skill registries)
- Public repo hygiene (gitignore, safety scanning, credential exclusion)
- CI configuration (GitHub Actions)
- Frontend and backend (React + Tailwind + FastAPI)
- Documentation at the right level of detail
