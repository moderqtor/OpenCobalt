# Coding

Coding work is a specialized path, not ordinary Chat. OpenCobalt currently
runs coding-agent mutations only through Cursor ACP, in a staged workspace,
with explicit promotion into the authoritative repository.

This is repository containment. It is not host OS sandboxing. Provider
processes can still touch the host; OpenCobalt detects and records unsolicited
writes outside the staged tree after the fact.

## Flow

```
goal + conversation project_path
  -> capability role coding_analysis or coding_agent
  -> eligible runtime (coding_agent: Cursor ACP only)
  -> coding Mission for coding_agent
  -> staged workspace for mutations
  -> provider execution
  -> provider-action approvals where requested
  -> ChangeSet
  -> staged pytest verification when tests exist
  -> explicit promotion
  -> authoritative repository
```

Ordinary Chat cannot grant repository mutation. `coding_agent` without a
project path is rejected.

## Capability roles

| Role | When | Workspace |
|---|---|---|
| `coding_analysis` | Repo questions, read-oriented inspection | Authoritative repo, Cursor ACP mode `ask`. No ChangeSet. |
| `coding_agent` | Mutating implementation with an attached project path | Staged workspace, Cursor ACP mode `agent`. ChangeSet required for promotion. |

Classification lives in `src/opencobalt/personal_ai/router.py`. Mission
creation lives in `src/opencobalt/personal_ai/coding.py` and `service.py`.

## Runtimes

| Runtime | Analysis | Agent | Staging |
|---|---|---|---|
| Cursor ACP | Yes | Yes | Yes, agent only |
| Antigravity | Advertised in routing | No | No |
| Claude Code / Codex | No | No | No |

Cursor uses the official `agent acp` stdio JSON-RPC interface with
`cursor_login`. OpenCobalt does not send `--force`, `--yolo`, `--api-key`, or
`allow-always`. Local-only requests exclude Cursor.

## Staging and ChangeSets

`StagingController` (`src/opencobalt/personal_ai/staging.py`):

1. Creates a git worktree at HEAD when possible, otherwise a filtered copy.
2. Points the coding-agent working directory at that staged path.
3. Builds a ChangeSet from staged vs authoritative files.
4. Runs discovered `test_*.py` files in the staged tree with isolated pytest.
5. Promotion is an explicit apply/reject API used by Chat and Missions.

Apply copies allowed files into the authoritative tree after conflict checks
(HEAD moved, overlapping dirty files, path policy, missing staging). Path
policy blocks `.env`, `.git`, credentials, and traversal. Failed verification
does not silently apply changes; it records a limitation and still requires
explicit promotion.

Dirty uncommitted work in the authoritative repo is not copied into the
worktree. Coding-analysis can still mutate the authoritative repo if the
provider writes there; OpenCobalt records that limitation and does not
promote those writes.

## Approvals

Two layers:

1. Live ACP `session/request_permission` requests become Approval Bridge
   records. The UI shows Allow once / Deny. Black-risk and mutating asks on
   non-agent surfaces are denied.
2. Promotion is a separate ChangeSet apply/reject action. Apply is the gate
   that modifies the authoritative repository.

ACP plans are not auto-approved. ACP questions have no UI and are skipped.

## What this does not do

- Full OS sandboxing or network isolation of Cursor
- Coding-agent execution through Claude, Codex, or Antigravity
- Silent writes to the authoritative repository
- Proof that staged tests equal production correctness

See [CURSOR_RUNTIME_ADAPTER.md](CURSOR_RUNTIME_ADAPTER.md) for the generic
Cursor CLI adapter used outside this Personal AI path, and
[SECURITY.md](../SECURITY.md) for trust boundaries.
