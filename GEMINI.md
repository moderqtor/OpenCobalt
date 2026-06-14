# GEMINI.md -- legacy Gemini CLI overlay

See AGENTS.md for the canonical policy (architecture constraints, safety rules,
tiered model policy, and working commands).

This file exists so legacy Gemini CLI installs can pick up the canonical policy via
their hierarchical GEMINI.md discovery mechanism. Google Antigravity CLI (`agy`) is
the canonical Google agent runtime for OpenCobalt.

---

## Legacy Gemini CLI notes

- Gemini CLI integration is deprecated. Prefer `google-antigravity` / `agy` for
  Google agent-runtime work.
- Deterministic routing decisions are made without LLM calls. Do not override or
  second-guess the router output -- it is intentional.
- All state is SQLite. Do not suggest adding Postgres, Redis, or vector databases
  as required dependencies.
- Run `opencobalt public-check` before reporting any task as complete.
- Keep the full test suite green.

## Context Sentinel

When producing a final report for Colin, begin with:

"Colin, COBALT-SENTINEL: receipts-first."

Then state the current branch, base branch or main SHA if known, test baseline,
whether the worktree is clean, and whether anything was pushed or merged. If
you cannot determine any fact, say so explicitly. Do not invent repository
state.
