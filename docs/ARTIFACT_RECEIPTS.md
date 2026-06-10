# Artifact Receipts

OpenCobalt records evidence for agent work as hashed artifacts referenced by
work receipts. This document covers the artifact model; see
`docs/EXECUTION_LAYER.md` for the execution slice that produces them.

## Model

An execution artifact is a pointer to a local file plus its integrity proof:

| Field | Meaning |
|-------|---------|
| `artifact_id` | UUID |
| `session_id` / `plan_id` / `execution_id` | Optional links into the provenance chain |
| `source_runtime` | Which runtime produced the file (`google-antigravity`, `ollama`, `noop`, `manual`) |
| `artifact_type` | One of the types below |
| `path` | Absolute path to the file on disk |
| `sha256` | SHA-256 of the file bytes at attach time |
| `size_bytes` | File size at attach time |
| `summary` | Optional one-line description |

Types: `plan`, `command_output`, `stdout`, `stderr`, `report`,
`inspection_report`, `diff`, `test_output`, `log`, `screenshot`,
`browser_recording`, `unknown`. Unrecognized types normalize to `unknown`.

## Hashing

SHA-256 over streamed file bytes (1 MiB chunks, large files are never loaded
whole). Verification recomputes the hash:

- match: `verified`
- mismatch: `failed` (the file changed after attach)
- file missing: `failed` with reason `file missing`

A receipt that references multiple artifacts verifies as `verified` only when
every artifact passes; `partial` when some pass; `failed` when none do.

## Commands

```
opencobalt artifacts attach <path> [--type TYPE] [--source RUNTIME]
                            [--plan PLAN_ID] [--execution EXEC_ID]
                            [--summary TEXT]
opencobalt artifacts verify <artifact_id>
opencobalt artifacts list [--type TYPE] [--plan PLAN_ID] [--limit N]
```

## Honest scope

- Hashing proves integrity, not safety. A verified artifact can still contain
  wrong, harmful, or sensitive content.
- Artifacts are plain files on local disk. Captured stdout/stderr may include
  sensitive data from the task. Treat `.opencobalt/artifacts/` accordingly;
  it is not committed and `opencobalt public-check` should pass before any
  push.
- Receipts store paths, not file contents. Deleting an artifact file makes
  its receipt fail verification by design.
