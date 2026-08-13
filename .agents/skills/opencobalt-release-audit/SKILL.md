---
name: opencobalt-release-audit
description: Verify git cleanliness, baseline tests, and report status before release.
---

# /opencobalt-release-audit

1. Inspect `git status -sb`.
2. Confirm worktree cleanliness.
3. Run full verification gates.
4. Report branch, test baseline, worktree, and remaining risk in plain language.
