# GEMINI.md -- Gemini CLI overlay

See AGENTS.md for the canonical policy (architecture constraints, safety rules,
tiered model policy, and working commands).

This file exists so Gemini CLI picks up the canonical policy via its hierarchical
GEMINI.md discovery mechanism.

---

## Gemini CLI notes

- You are an executive-tier tool for this project. Handle architecture, security
  analysis, large codebase questions, and final code review.
- Deterministic routing decisions are made without LLM calls. Do not override or
  second-guess the router output -- it is intentional.
- All state is SQLite. Do not suggest adding Postgres, Redis, or vector databases
  as required dependencies.
- Run `opencobalt public-check` before reporting any task as complete.
- Baseline: 214 passing tests. All must stay green.
