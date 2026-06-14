# Cursor Runtime Adapter v0

Cursor Runtime Adapter v0 makes Cursor visible to OpenCobalt's execution layer
only through the normalized adapter receipt contract.

It is not a generic Cursor checkbox. The integration registry can report that
the editor is installed, but execution support is decided by the runtime adapter:

```
opencobalt adapters inspect cursor
```

## Capability Levels

- `unavailable`: no Cursor app and no real `cursor` executable were found.
- `partial`: Cursor is installed, and in the best case local help proves
  `cursor agent --print --mode plan` is available.
- `untrusted`: a local Cursor surface exists but cannot produce enough
  receipt-compatible evidence.

Cursor is not `full` in v0. OpenCobalt can verify its own invocation, captured
artifacts, event count, receipt metadata, and provenance references. It cannot
verify Cursor account state, remote model behavior, or Cursor's internal
read-only enforcement.

## Discovery

The adapter checks:

- `cursor` on PATH, only if it resolves to a real executable
- `/Applications/Cursor.app`
- `~/Applications/Cursor.app`
- the bundled app CLI at `Contents/Resources/app/bin/cursor`
- `cursor agent --help` output, only for local capability evidence

The adapter does not launch the editor during discovery and does not read or
store credentials, cookies, tokens, project auth, user settings, or raw
environment variables.

## Invocation

The only executable path in v0 is read-only planning:

```
cursor agent --print --mode plan --output-format text -- "task"
```

Optional flags are included only when help output advertises them:

- `--model <model>`
- `--sandbox enabled`

The adapter never adds:

- `--cloud`
- `--force`
- `--browser`
- `--approve-mcps`
- `login`
- `logout`
- `--api-key`

## Receipts

Cursor execution goes through `ExecutionEngine`:

1. deterministic risk classification
2. dry-run default
3. policy gate
4. normalized invocation hash
5. stdout/stderr artifact capture
6. artifact hash verification
7. normalized adapter receipt
8. provenance references

Cursor receipts include `adapter_id: cursor`, capability snapshot hash,
invocation hash, environment policy, risk level, event count, artifact hashes,
verification status, limitations, and provenance references.

## CLI Behavior

`opencobalt adapters list` shows Cursor with the current local availability and
verifiability level.

`opencobalt adapters inspect cursor` shows:

- availability
- executable or app path
- snapshot hash
- verifiability
- network and credential flags
- supported artifact types
- capability evidence
- limitations

`opencobalt integrations check` can report the Cursor editor as installed. That
is not a runtime execution claim. Runtime execution requires adapter evidence.

## Limits

- Cursor may require a signed-in account or API credential outside OpenCobalt.
- Cursor may use networked model services.
- OpenCobalt does not control Cursor cloud/background agents in v0.
- OpenCobalt does not approve Cursor MCPs, browser automation, deploys,
  publishes, spending, messages, or permission bypasses.
- Hash verification proves captured artifact integrity only. It does not prove
  the Cursor answer is correct or safe.
