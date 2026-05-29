# Employer and Recruiter Notes

## Resume Bullets

- Built OpenCobalt, a local-first AI orchestration control plane in Python that routes tasks across Claude Code, Codex CLI, Gemini CLI, Cursor, and Ollama using a deterministic scoring router with tiered risk classification
- Designed and implemented a SQLite-backed memory ledger (Pydantic v2 schemas, stdlib sqlite3) with 58 passing tests covering events, routing decisions, verification results, and memory records
- Built a public safety scanner that detects hardcoded secrets, private vault path references, oversized artifacts, and .env files before any repo push

## LinkedIn Bullets

- Designed OpenCobalt's routing tier system, which separates worker-tier local LLMs (Ollama) from executive-tier AI tools (Claude, Codex, Gemini) based on task risk and reversibility
- Built a clean public repo from private AI infrastructure work by writing a systematic extraction audit, identifying credential leakage risks in source material, and rewriting extracted code rather than copying it
- Applied an applied analytics mindset to AI orchestration: route decisions are scored numerically, recorded to SQLite, and designed for future aggregation and analysis

## GitHub Pinned Description

Local-first AI orchestration and memory control plane. Routes tasks across Claude Code, Codex CLI, Gemini CLI, Cursor, and Ollama. SQLite ledger, deterministic router, public safety scanner. Python, Pydantic, Typer.

## Recruiter Explanation (30 seconds)

OpenCobalt is a command-line tool that helps developers manage AI-assisted development workflows. Instead of switching between five AI tools with no memory of what happened, OpenCobalt routes each task to the right tool, logs everything to a local database, and runs a safety check before anything gets pushed to GitHub. It is practical infrastructure, not a research demo.

## Technical Interviewer Explanation

The core is a deterministic task router that scores tasks against tool profiles using keyword matching. No LLM inference in the router itself -- it is fast, testable, and predictable. The ledger is SQLite via the standard library, with Pydantic v2 schemas for all domain objects. The public safety scanner uses regex patterns on file content and catches real classes of mistakes I have seen in private AI development work.

The architectural constraint is tier separation: local Ollama models are worker-tier only (summarization, tagging, extraction) and are explicitly excluded from executive-tier tasks (architecture decisions, security review, public-facing content). This was a deliberate design choice, not a default.

## What Not to Overclaim

- This is not a production system. It is a personal development tool that I built and use.
- The router is deterministic and keyword-based. It does not do semantic inference.
- The tests are unit and integration tests against real SQLite databases -- not end-to-end tests of real AI tool outputs.
- The UI layer is planned but not implemented. All interaction is CLI.
- Cost control and optional API adapters are documented and designed but not yet implemented.
