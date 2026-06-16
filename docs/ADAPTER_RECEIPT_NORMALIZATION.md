# Adapter Receipt Normalization v1

Adapter Receipt Normalization v1 defines the minimum contract for any runtime
adapter that wants to execute work under OpenCobalt.

Adding a runtime is not adding a thin wrapper around a tool command. It is adding
a verifiable worker type with declared capabilities, a bounded invocation, policy
gating, captured events, hashed artifacts, a normalized work receipt, provenance
links, and later outcome feedback.

## Contract

Every execution adapter must support this loop:

```
capability discovery
  -> normalized invocation plan
  -> policy boundary
  -> execution event stream
  -> artifact capture
  -> normalized work receipt
  -> verification
  -> provenance edge
  -> outcome feedback
```

The execution layer owns this contract. Integrations can say that a tool exists,
but runtime adapters must produce receipt evidence.

External runtime task execution is only allowed through `ExecutionEngine`.
Discovery-only subprocesses are allowed only for help, version, or install
checks with short timeouts and no user task text. Legacy helpers that cannot
produce the normalized contract must return a blocked message that points to
`opencobalt run "TASK" --runtime <adapter-id> --dry-run`.

## RuntimeCapabilitySnapshot

Each adapter emits a normalized capability snapshot:

- `adapter_id`, `adapter_name`, and optional `adapter_version`
- `executable_path` and `available`
- supported capability names plus raw descriptive capability evidence
- supported artifact types
- dry-run, non-interactive, and JSON-output support flags
- `requires_network` and `requires_credentials`
- `max_safe_risk`
- limitations and a stable `snapshot_hash`
- adapter verifiability level

Capability snapshots are descriptive, not permissive. Unknown capability evidence
does not authorize execution. Missing executables produce unavailable snapshots
instead of crashing adapter inspection.

## NormalizedInvocation

Each receipt stores the bounded invocation OpenCobalt intended to run:

- stable `invocation_hash`
- canonical adapter id
- optional approval and mission linkage
- redacted argv or structured action
- cwd
- environment policy, such as `inherited_redacted`
- expected artifact types
- risk level, dry-run flag, and timeout

OpenCobalt never stores raw environment variables in invocation metadata.

## NormalizedAdapterReceipt

The existing `WorkReceipt` remains the durable receipt record. V1 enriches it
with normalized metadata rather than replacing it.

Mandatory normalized receipt fields include:

- receipt id and invocation id
- adapter id
- optional mission, approval, mission step, and approval step references
- start and finish timestamps when execution occurred
- exit code and status
- risk level
- command hash and plan hash
- capability snapshot hash
- artifact hashes
- event count
- verification status
- limitations
- provenance references
- verifiability level

`verification_status` remains hash verification only: `unverified`, `verified`,
`partial`, or `failed`.

## Verifiability Levels

Adapters and receipts use explicit confidence levels:

- `full`: capability snapshot, invocation hash, receipt, artifact hashes, and event stream exist.
- `partial`: receipt and invocation metadata exist, but artifact capture or runtime evidence is limited.
- `dry_run_only`: only a bounded plan and receipt were created.
- `unavailable`: runtime was discovered as missing or unusable.
- `untrusted`: the adapter cannot produce enough normalized evidence.

Weak or unverifiable adapters are marked limited, not trusted.

## Current Adapters

Adapter Receipt Normalization v1 covers the existing execution adapters:

- `noop`: test and pipeline adapter, full verifiability when executed.
- `ollama`: local model runtime, unavailable when the executable is missing.
- `google-antigravity`: canonical Antigravity runtime id, with legacy Gemini CLI
  aliases resolved to the canonical adapter. Unknown runtime capabilities remain
  unknown.
- `claude-code`: Claude Code runtime id. Discovery checks a real `claude`
  executable on PATH plus local `claude --version` and `claude --help`
  evidence. Execution is available only when local help proves `--print`,
  `--output-format text`, and `--permission-mode plan`. Receipts are partial
  because Claude account state, network model behavior, and internal permission
  enforcement live outside OpenCobalt.
- `codex-cli`: Codex CLI runtime id. Discovery checks a real `codex`
  executable on PATH plus local `codex --version`, `codex --help`, and
  `codex exec --help` evidence. Execution is available only when local help
  proves non-interactive `exec`, `--sandbox read-only`, and
  `--ask-for-approval never`. Receipts are partial because Codex account state,
  network model behavior, and internal permission enforcement live outside
  OpenCobalt.
- `cursor`: Cursor Agent runtime id. Discovery checks a real `cursor`
  executable on PATH and common macOS `Cursor.app` locations. Execution is
  only available when local help proves `cursor agent --print --mode plan`
  exists. Receipts are partial because Cursor's account, model service, and
  read-only enforcement live outside OpenCobalt.

## CLI

```
opencobalt adapters list
opencobalt adapters inspect ADAPTER_ID
opencobalt receipts inspect RECEIPT_ID
opencobalt receipts verify RECEIPT_ID
```

`receipts inspect` shows the normalized adapter id, capability snapshot hash,
invocation hash, environment policy, verifiability level, event count, and
artifact hash count.

## Safety Boundaries

- No raw environment dumps.
- No credential storage.
- No private keys, seed phrases, API keys, cookies, or tokens in receipt metadata.
- Missing runtime executables create skipped, auditable receipts instead of
  starting a subprocess.
- External runtime task execution outside `ExecutionEngine` is blocked.
- Discovery-only subprocesses are limited to help, version, or install checks
  with short timeouts and no task text.
- Policy gates remain unchanged: dry-run by default, green/yellow need
  `--execute`, red needs `--execute --yes`, black is blocked.
- No background daemon, network fetcher, deploy path, publish path, spend path,
  auto-merge, or push behavior is introduced.

## Cursor Runtime Adapter v0

Cursor is a runtime adapter only through the normalized receipt contract. The
integration registry can report that the editor is installed, but runtime
support is determined by:

```
opencobalt adapters inspect cursor
```

Discovery is conservative:

- `unavailable`: no Cursor app and no real `cursor` executable were found.
- `partial`: Cursor is installed, or `cursor agent --print --mode plan` was
  discovered, but runtime trust is limited.
- `untrusted`: a local Cursor surface exists but cannot produce a
  receipt-compatible non-interactive plan command.

The only command OpenCobalt builds in v0 is:

```
cursor agent --print --mode plan --output-format text -- "task"
```

Optional `--model` and `--sandbox enabled` flags are included only when local
help output advertises them. OpenCobalt never adds Cursor `--cloud`, `--force`,
`--browser`, `--approve-mcps`, `login`, `logout`, or `--api-key` flags.

Cursor execution still flows through `ExecutionEngine`: deterministic risk
classification, dry-run default, policy gate, captured stdout/stderr artifacts,
hash verification, normalized receipt metadata, and provenance references.

## Claude Code Runtime Adapter v0

Claude Code is a runtime adapter only through the normalized receipt contract.
The integration registry can report that `claude` is installed, but runtime
support is determined by:

```
opencobalt adapters inspect claude-code
```

Discovery is conservative:

- `unavailable`: no `claude` executable was found.
- `partial`: `claude` is installed or local help/version evidence was
  discovered. If safe headless invocation is not proven, support is
  discovery-only.
- `full`: not claimed in v0.

The only command OpenCobalt builds in v0 is a read-only planning prompt through
local help-proven print mode:

```
claude --print --output-format text --permission-mode plan "OpenCobalt read-only planning request:
TASK"
```

Optional `--model`, `--no-session-persistence`, `--safe-mode`, `--no-chrome`,
and empty MCP config flags are included only when local help advertises them.
OpenCobalt never adds dangerous permission bypass flags, MCP auto-approval,
browser-control, auth, token, deploy, publish, spend, or message paths.

Claude Code execution still flows through `ExecutionEngine`: deterministic risk
classification, dry-run default, policy gate, captured stdout/stderr artifacts,
hash verification, normalized receipt metadata, and provenance references.
OpenCobalt does not rely on Claude Code's internal permission system alone.

## Codex Runtime Adapter v0

Codex CLI is a runtime adapter only through the normalized receipt contract.
The integration registry can report that `codex` is installed, but runtime
support is determined by:

```
opencobalt adapters inspect codex-cli
```

Discovery is conservative:

- `unavailable`: no `codex` executable was found.
- `partial`: `codex` is installed or local help/version evidence was
  discovered. If safe headless invocation is not proven, support is
  discovery-only.
- `full`: not claimed in v0.

The only command OpenCobalt builds in v0 is a read-only planning prompt through
local help-proven exec mode:

```
codex --sandbox read-only --ask-for-approval never exec \
  [--json] [--ephemeral] [--ignore-user-config] [--color never] \
  "OpenCobalt read-only planning request:
TASK"
```

Optional `--model` is included only when local help advertises it. OpenCobalt
never adds dangerous approval/sandbox bypass flags, danger-full-access sandbox,
credential/auth/login/logout paths, MCP management, app-server, remote-control,
mcp-server, exec-server, apply, cloud, update, browser-control, deploy, publish,
spend, message, or web search paths.

Codex execution still flows through `ExecutionEngine`: deterministic risk
classification, dry-run default, policy gate, captured stdout/stderr artifacts,
hash verification, normalized receipt metadata, and provenance references.
OpenCobalt does not rely on Codex internal permissioning alone.

## Next Branch

After Codex Runtime Adapter v0, the next adapter branch should add
outcome-weighted adapter routing. Long-running mission execution should wait
until runtime receipts and outcome signals are in place.
