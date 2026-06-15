# Codex Runtime Adapter v0

Codex Runtime Adapter v0 makes OpenAI Codex CLI visible to OpenCobalt only
through the normalized adapter receipt contract. Codex is treated as an
external worker whose output is evidence, not authority.

The integration registry can report that `codex` is installed. Runtime support
is decided by the execution adapter:

```
opencobalt adapters inspect codex-cli
```

## Capability Levels

- `unavailable`: no executable named `codex` was found on PATH.
- `partial`: Codex CLI is installed, or local `codex --help`,
  `codex exec --help`, or `codex --version` evidence was discovered. If safe
  headless invocation is not proven, support is discovery-only.
- `full`: not claimed in v0.
- `untrusted`: reserved for a local Codex surface that cannot produce enough
  bounded evidence for OpenCobalt.

Codex remains `partial` in v0. OpenCobalt can verify its own invocation,
captured artifacts, event count, receipt metadata, and provenance references. It
cannot verify Codex account state, remote model behavior, or Codex internal
permission enforcement.

## Discovery

The adapter checks:

- `codex` on PATH, only if it resolves to an executable file
- `codex --version`, with a short timeout
- `codex --help`, with a short timeout
- `codex exec --help`, with a short timeout
- advertised `exec` non-interactive support
- advertised `--sandbox read-only`
- advertised `--ask-for-approval never`
- optional `--json`, `--ephemeral`, `--ignore-user-config`, `--color never`,
  and `--model`, only when help advertises them

This branch uses local CLI help as the discovery source. It does not assume
undocumented Codex CLI syntax and does not require official docs to be available
during inspection. If official docs and local help disagree, implementation
follows local help.

Discovery does not run a task, open a browser, start a daemon, read credentials,
or store raw environment variables.

## Invocation

Execution is available only when local help proves the bounded non-interactive
surface. The default command shape is:

```
codex --sandbox read-only --ask-for-approval never exec \
  [--json] \
  [--ephemeral] \
  [--ignore-user-config] \
  [--color never] \
  "OpenCobalt read-only planning request:
TASK"
```

Optional `--model MODEL` is included only when local help advertises model
selection. The task is passed as a final positional prompt with an OpenCobalt
read-only prefix so task text is not treated as a CLI flag.

The adapter never adds:

- `--dangerously-bypass-approvals-and-sandbox`
- `--dangerously-bypass-hook-trust`
- `--sandbox danger-full-access`
- login, logout, auth, token, credential, API-key, MCP management, app-server,
  remote-control, mcp-server, exec-server, apply, cloud, update, browser-control,
  deploy, publish, spend, message, or web search paths

OpenCobalt does not rely on Codex internal permissioning alone. The
ExecutionEngine policy gate remains authoritative: dry-run by default,
green/yellow require `--execute`, red requires `--execute --yes`, and black is
blocked.

## Receipts

Codex execution goes through `ExecutionEngine`:

1. deterministic risk classification
2. dry-run default
3. policy gate
4. normalized invocation hash
5. stdout/stderr artifact capture
6. artifact hash verification
7. normalized adapter receipt
8. provenance references

Codex receipts include `adapter_id: codex-cli`, capability snapshot hash,
invocation hash, environment policy, risk level, event count, artifact hashes,
verification status, limitations, and provenance references.

## CLI Behavior

`opencobalt adapters list` shows Codex CLI with local availability and the
current verifiability level.

`opencobalt adapters inspect codex-cli` shows:

- availability
- executable path
- snapshot hash
- capability level
- network and credential flags
- supported artifact types
- capability evidence
- limitations

`opencobalt integrations check` can report the `codex` executable as installed.
That is not a runtime execution claim. Runtime execution requires adapter
evidence from `opencobalt adapters inspect codex-cli`.

## Limits

- Codex may require credentials or account state outside OpenCobalt.
- Codex may use networked model services.
- OpenCobalt does not verify Codex model answers for semantic correctness in
  v0.
- Hash verification proves captured artifact integrity only.
- If safe headless invocation is not proven locally, support is partial and
  discovery-only.
- The adapter does not run unrestricted/full-auto modes and does not mutate the
  repository unless a future branch explicitly adds a bounded, approved,
  receipt-backed execution mode.
