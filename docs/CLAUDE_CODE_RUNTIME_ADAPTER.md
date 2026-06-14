# Claude Code Runtime Adapter v0

Claude Code Runtime Adapter v0 makes Claude Code visible to OpenCobalt only
through the normalized adapter receipt contract. Claude Code is treated as an
external worker whose output is evidence, not authority.

The integration registry can report that `claude` is installed. Runtime support
is decided by the execution adapter:

```
opencobalt adapters inspect claude-code
```

## Capability Levels

- `unavailable`: no executable named `claude` was found on PATH.
- `partial`: Claude Code is installed, or local `claude --help` /
  `claude --version` evidence was discovered. Safe invocation may still be
  discovery-only if the required print and plan flags are missing.
- `full`: not claimed in v0.
- `untrusted`: reserved for a local surface that cannot produce enough bounded
  evidence for OpenCobalt.

Claude Code remains `partial` in v0. OpenCobalt can verify its own invocation,
captured artifacts, event count, receipt metadata, and provenance references. It
cannot verify Claude account state, remote model behavior, or Claude Code's
internal permission enforcement.

## Discovery

The adapter checks:

- `claude` on PATH, only if it resolves to an executable file
- `claude --version`, with a short timeout
- `claude --help`, with a short timeout
- advertised non-interactive `--print`
- advertised `--output-format text`
- advertised `--permission-mode plan`
- safe limiting flags, only when help advertises them

This branch uses local CLI help as the discovery source. It does not assume
undocumented Claude Code syntax and does not require official docs to be
available during inspection.

Discovery does not run a task, open a browser, start a daemon, read credentials,
or store raw environment variables.

## Invocation

Execution is available only when local help proves the bounded print and plan
surface. The default command shape is:

```
claude --print --output-format text --permission-mode plan \
  [--model MODEL] \
  [--no-session-persistence] \
  [--safe-mode] \
  [--no-chrome] \
  [--strict-mcp-config --mcp-config "{}"] \
  "OpenCobalt read-only planning request:
TASK"
```

Optional flags are included only when `claude --help` advertises them. The task
is passed as a final positional prompt with an OpenCobalt read-only prefix so
task text is not treated as a CLI flag.

The adapter never adds:

- `--dangerously-skip-permissions`
- `--allow-dangerously-skip-permissions`
- `--permission-mode bypassPermissions`
- `--allowedTools`
- `--disallowedTools`
- `--max-budget-usd`
- auth, token, login, logout, browser-control, deploy, publish, spend, or
  message commands
- MCP auto-approval paths

OpenCobalt does not rely on Claude Code's internal permission system alone. The
ExecutionEngine policy gate remains authoritative: dry-run by default,
green/yellow require `--execute`, red requires `--execute --yes`, and black is
blocked.

## Receipts

Claude Code execution goes through `ExecutionEngine`:

1. deterministic risk classification
2. dry-run default
3. policy gate
4. normalized invocation hash
5. stdout/stderr artifact capture
6. artifact hash verification
7. normalized adapter receipt
8. provenance references

Claude Code receipts include `adapter_id: claude-code`, capability snapshot
hash, invocation hash, environment policy, risk level, event count, artifact
hashes, verification status, limitations, and provenance references.

## CLI Behavior

`opencobalt adapters list` shows Claude Code with local availability and the
current verifiability level.

`opencobalt adapters inspect claude-code` shows:

- availability
- executable path
- snapshot hash
- capability level
- network and credential flags
- supported artifact types
- capability evidence
- limitations

`opencobalt integrations check` can report the `claude` executable as installed.
That is not a runtime execution claim. Runtime execution requires adapter
evidence from `opencobalt adapters inspect claude-code`.

## Limits

- Claude Code may require credentials or account state outside OpenCobalt.
- Claude Code may use networked model services.
- OpenCobalt does not verify Claude Code's model answer for semantic
  correctness in v0.
- Hash verification proves captured artifact integrity only.
- If safe headless invocation is not proven locally, support is partial and
  discovery-only.
