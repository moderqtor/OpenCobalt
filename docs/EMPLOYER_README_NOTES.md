# Employer and Recruiter Notes

## Resume Bullets

- Built OpenCobalt, a local-first AI orchestration CLI in Python that routes tasks across Claude Code, Codex CLI, Gemini CLI, Cursor, and Ollama using a deterministic scoring router with tiered model classification and a SQLite session ledger
- Implemented persistent agent memory with SQLite-backed MemoryBridge, session observability tracking, agent benchmarking with composite scoring, and repo-hygiene public-check tooling; 244 tests, ruff lint clean, GitHub Actions CI

## LinkedIn Bullets

- Designed OpenCobalt's routing tier system, which separates worker-tier local LLMs (Ollama) from executive-tier AI tools (Claude, Codex, Gemini) based on task risk and reversibility
- Built a clean public repo from private AI infrastructure work by writing a systematic extraction audit, identifying credential leakage risks in source material, and rewriting extracted code rather than copying it
- Applied an applied analytics mindset to AI orchestration: route decisions are scored numerically, recorded to SQLite, tagged with session IDs, and surfaced via a stats command

## GitHub Pinned Description

Local-first AI orchestration and memory control plane. Routes tasks across Claude Code, Gemini CLI, Cursor, Aider, Context7, and Ollama. SQLite ledger, deterministic router, agents and skills registries, session tracking, public safety scanner, live React dashboard. Python, Pydantic, Typer. 244 tests.

## Recruiter Explanation (30 seconds)

OpenCobalt is a command-line tool that helps developers manage AI-assisted development workflows. Instead of switching between five AI tools with no memory of what happened, OpenCobalt routes each task to the right tool, logs everything to a local database, and runs a safety check before anything gets pushed to GitHub. It is practical infrastructure, not a research demo.

## Technical Interviewer Explanation

The core is a deterministic task router that scores tasks against tool profiles using keyword matching. No LLM inference in the router itself -- it is fast, testable, and predictable. The ledger is SQLite via the standard library, with Pydantic v2 schemas for all domain objects. The public safety scanner uses regex patterns on file content and catches real classes of mistakes I have seen in private AI development work.

The system includes an agents registry, a skills registry, and an integrations registry -- each with a base class and concrete implementations. The code-reviewer agent uses the file-reader skill to extract real metrics from source files rather than returning hardcoded output. Session tracking tags every route decision with a session ID, so you can reconstruct what was routed during any given work session.

The architectural constraint is tier separation: local Ollama models are worker-tier only (summarization, tagging, extraction) and are explicitly excluded from executive-tier tasks (architecture decisions, security review, public-facing content). This was a deliberate design choice, not a default.

Ruff runs in CI. 244 tests cover units, ledger integration, router logic, and CLI commands.

## What Not to Overclaim

- This is not a production system. It is a personal development tool that I built and use.
- The router is deterministic and keyword-based. It does not do semantic inference.
- The tests are unit and integration tests against real SQLite databases -- not end-to-end tests of real AI tool outputs.
- The UI layer is a live React dashboard wired to a FastAPI backend. Start both with `opencobalt ui`.
- API adapters (Anthropic, OpenAI, Google) are next on the roadmap, not yet implemented.
