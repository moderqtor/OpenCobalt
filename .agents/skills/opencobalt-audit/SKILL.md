---
name: opencobalt-audit
description: Establish current OpenCobalt repository baseline, git state, and quality gate status.
---

# /opencobalt-audit

Execute baseline audit:
1. Record `git status -sb` and HEAD SHA.
2. Run quality gates:
   - `.venv/bin/ruff check .`
   - `.venv/bin/opencobalt public-check`
   - `.venv/bin/pytest`
3. Produce a receipts-first baseline summary.
