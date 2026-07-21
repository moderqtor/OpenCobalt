---
name: opencobalt-release-audit
description: Verify git cleanliness, baseline tests, and sentinel output before release.
---

# /opencobalt-release-audit

1. Inspect `git status -sb`.
2. Confirm worktree cleanliness.
3. Run full verification gates.
4. Format final report beginning with sentinel: `Colin, COBALT-SENTINEL: receipts-first.`
