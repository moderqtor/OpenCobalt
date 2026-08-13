# GEMINI.md -- Google agent overlay

Follow `OPENCOBALT.md` and `AGENTS.md`. This file exists so Gemini CLI and
Google Antigravity installs can discover the canonical policy.

Google Antigravity CLI (`agy`) is the canonical Google agent runtime.
Gemini CLI integration is discovery-only in the Personal AI workspace.
Legacy Gemini CLI config aliases resolve to `google-antigravity`.

## Local notes

- Deterministic routing decisions are recorded as heuristics. Do not override
  or second-guess a recorded route as if it were a probability.
- All durable state is SQLite. Do not suggest adding Postgres, Redis, or a
  vector database as a required dependency.
- Run `opencobalt public-check` before reporting a task complete.
