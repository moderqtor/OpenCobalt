---
name: opencobalt-audit
description: Establish current OpenCobalt repository baseline, git state, and quality gate status.
---

# /opencobalt-audit

1. Record `git status -sb` and HEAD SHA.
2. Run quality gates:
   - `uv run ruff check .`
   - `uv run opencobalt public-check`
   - `uv run pytest`
3. Report branch, baseline, worktree, and failures without branding slogans.
