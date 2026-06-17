# Autonomy Envelopes

Autonomy is the amount of local work OpenCobalt may do automatically.
Authority is permission to cross outward or irreversible boundaries. The two
are separate.

Typed definitions live in `src/opencobalt/core/autonomy_envelopes.py`.

## Envelope Summary

| Envelope | Purpose | Writes | Subprocess | Commit | Remote authority |
|----------|---------|--------|------------|--------|------------------|
| `observe` | Read-only status and inspection | none | discovery only | no | no |
| `plan` | Deterministic planning | none | discovery only | no | no |
| `dry_run` | Safe dry-run receipts | `.opencobalt` | dry-run only | no | no |
| `sandbox_exec` | Local tests and safe commands | generated artifacts | policy-gated local | no | no |
| `repo_autopilot` | Local repo edits and optional local commits | repo, `.opencobalt` | policy-gated local | yes | no |
| `pr_drafter` | Local PR materials as artifacts | repo, `.opencobalt` | policy-gated local | yes | no |
| `autonomous_lab` | High local experimentation | repo, `.opencobalt`, artifacts | policy-gated local | no | no |
| `operator_yolo` | Maximum local autonomy | repo, `.opencobalt`, artifacts | policy-gated local | yes | no |
| `production_guarded` | Production-adjacent planning | `.opencobalt`, artifacts | dry-run only | no | no |

Remote authority means push, merge, deploy, publish, spend, external messages,
or secret/auth access. Default envelopes do not grant it.

## Operator YOLO

`operator_yolo` is intentionally high-autonomy locally. It can branch, write
local repo files, run policy-gated local commands, and create local commits.
It still blocks secrets, spend, deploy, publish, external messages, push, merge,
and irreversible remote actions.

## Cognitive Budgets

| Budget | Use | Subagents | Depth | Runtime iterations | Research |
|--------|-----|-----------|-------|--------------------|----------|
| `low` | Status and small plans | 0 | 0 | 1 | no |
| `medium` | Small bug triage and planning | 2 | 1 | 3 | no |
| `high` | Multi-step repo work | 4 | 2 | 8 | no |
| `xhigh` | Longer local autonomy loops | 6 | 3 | 16 | no |
| `research` | Evidence gathering and comparison | 3 | 2 | 6 | yes |

External runtimes are not architecture. They are optional receipt-backed
workers selected inside an envelope.
