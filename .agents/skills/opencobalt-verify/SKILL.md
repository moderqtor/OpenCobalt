---
name: opencobalt-verify
description: Run full quality gates and verify zero regressions.
---

# /opencobalt-verify

1. Run `.venv/bin/ruff check .`
2. Run `.venv/bin/opencobalt public-check`
3. Run `.venv/bin/pytest`
4. Classify any failure as introduced vs pre-existing.
