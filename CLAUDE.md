# CLAUDE.md -- Claude Code overlay

See AGENTS.md for the canonical policy (architecture constraints, safety rules,
tiered model policy, working commands, and what not to do).

---

## Claude Code-specific notes

**Response style:**
- Terse. One sentence per update while working.
- No trailing summaries of what you just did -- the diff shows it.
- No em dashes. No hype language.
- When referencing code, include `file_path:line_number`.

**Tool use:**
- Prefer dedicated tools (Read, Edit, Write) over Bash for file operations.
- Run independent tool calls in parallel.
- Call `advisor` before substantive work and before declaring a task complete.

**Testing:**
- Always run `python3 -m pytest -q` after any code change.
- Baseline: 965 passing tests, 1 warning (after Phase 22 Adapter Receipt
  Normalization v1). All must stay green.
- New code requires new tests. Use `tmp_path` from pytest fixtures for SQLite isolation.

**Commits:**
- Never push to GitHub without explicit instruction.
- Local commits only.
- Co-author line: `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>`

**Public safety:**
- Run `opencobalt public-check` after any doc or config change.
- The scanner checks secret patterns in all files except `tests/` and `.opencobalt/`.
- Use `<placeholder>` style (with angle brackets) for any key values in docs to
  avoid tripping the secret pattern scanner.

## Context Sentinel

When producing a final report for Colin, begin with:

"Colin, COBALT-SENTINEL: receipts-first."

Then state:
- current branch
- base branch or main SHA if known
- test baseline
- whether worktree is clean
- whether anything was pushed or merged

If you cannot determine these facts, say so explicitly. Do not invent repository
state. If the sentinel is missing, stale, or paired with incorrect repo state,
assume context has degraded and pause for re-grounding.
