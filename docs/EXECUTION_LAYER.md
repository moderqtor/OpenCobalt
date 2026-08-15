# Receipt-Backed Execution v0

OpenCobalt's execution layer turns a routed task into a verifiable evidence
chain. Every agent action leaves a receipt.

The vertical slice:

```
route task -> create plan -> build safe command -> enforce policy
  -> run or dry-run -> capture output -> attach artifacts
  -> hash artifacts -> write receipt -> verify receipt
```

## Quick start

```
opencobalt run "summarize docs/ANTIGRAVITY.md" --runtime google-antigravity --dry-run
opencobalt run "hello" --runtime noop --execute
opencobalt run "hello" --runtime google-antigravity --execute --sandbox
opencobalt receipts list
opencobalt receipts inspect <receipt_id>
opencobalt receipts verify <receipt_id>
opencobalt artifacts attach report.md --type report --summary "audit findings"
opencobalt artifacts verify <artifact_id>
```

`opencobalt run` defaults to dry-run. A dry-run stores the plan and a receipt
with `verification_status: unverified` and never starts a subprocess.

## Runtime execution boundary

External runtime task execution is only allowed through `ExecutionEngine`.
Discovery-only subprocesses are allowed only for help, version, or install
checks with short timeouts and no user task text.

Legacy helper paths such as council model calls, pipeline tool steps,
shell launchers, `route --exec`, worker-tier Ollama agents, and direct auto-push
logic do not execute external workers. They return a blocked message that points
operators to `opencobalt run "TASK" --runtime <adapter-id> --dry-run`.

## Architecture

All code lives in `src/opencobalt/execution/`:

| Module | Responsibility |
|--------|----------------|
| `models.py` | `ExecutionPlan`, `ExecutionStep`, `ExecutionResult`, `ExecutionArtifact`, `WorkReceipt` (Pydantic) |
| `policy.py` | Deterministic risk classification and the execution gate |
| `adapters.py` | `RuntimeAdapter` protocol plus `claude-code`, `codex-cli`, `cursor`, `google-antigravity`, `ollama`, `noop` adapters |
| `runner.py` | Safe subprocess runner (argv lists, no shell, timeouts, output spill) |
| `artifacts.py` | Streaming SHA-256 hashing, attach, verify |
| `store.py` | SQLite persistence in `.opencobalt/ledger.db` |
| `engine.py` | `ExecutionEngine`: the full slice plus structured event emission |

## Adapter Receipt Normalization v1

V1 formalizes the receipt contract every execution adapter must satisfy. It does
adds the contract used by `cursor`, `noop`, `ollama`, and `google-antigravity`
adapters through the existing receipt store.

The normalized contract records:

- `RuntimeCapabilitySnapshot`: adapter id, name, executable path, availability,
  capability evidence, artifact types, network and credential requirements,
  limitations, verifiability level, and snapshot hash.
- `NormalizedInvocation`: stable invocation hash, canonical adapter id, redacted
  argv or structured action, cwd, environment policy, expected artifacts, risk,
  dry-run flag, and timeout.
- `AdapterExecutionEvent`: receipt-local view of execution events emitted by the
  existing event stream.
- `NormalizedAdapterReceipt`: invocation id, adapter id, command hash, plan hash,
  capability snapshot hash, artifact hashes, event count, verification status,
  limitations, and provenance references.

`WorkReceipt` remains the durable receipt model. V1 adds normalized metadata to
that model and the `work_receipts` table through additive columns, so older
receipt rows still load.

Adapter verifiability levels are `full`, `partial`, `dry_run_only`,
`unavailable`, and `untrusted`. Weak adapters are marked limited rather than
trusted.

## Policy gate

Risk is classified by deterministic keyword matching (no LLM):

| Risk | Examples | Execution rule |
|------|----------|----------------|
| green | read-only planning, summarization, static analysis | `--execute` |
| yellow | local file edits, test runs, generated artifacts | `--execute` |
| red | credential or environment access, deployment, publishing | `--execute --yes` |
| black | destructive filesystem operations, credential export | blocked, no override in v0 |

Dry-run is always allowed. Tasks mentioning `.env`, tokens, secrets, SSH keys,
private keys, browser profiles, cookies, credentials, deployment, package
publishing, production config, or API keys classify as red at minimum. The
final plan risk is the worst of the policy classifier, the router's risk
metadata, and the adapter's own view.

## Runtime adapters

An adapter never executes work directly. It detects the runtime, reports a
normalized capability snapshot, and builds a default-safe argv:

- `google-antigravity`: limited to the discovered non-interactive `--print`
  mode. `--model` and `--sandbox` are included only when discovered in local
  `agy --help`. `--dangerously-skip-permissions` is never added by default;
  the explicit unsafe override emits a RuntimeWarning and a policy event.
  If `--print` was not discovered, command construction fails cleanly.
- `cursor`: limited to discovered `cursor agent --print --mode plan`
  read-only planning. PATH binaries and common macOS `Cursor.app` locations
  are discovered without launching the editor. `--model` and
  `--sandbox enabled` are included only when local help advertises them.
  Cloud mode, force, browser automation, MCP auto-approval, login, logout,
  and API-key flags are never used.
- `claude-code`: limited to discovered `claude --print --output-format text`
  with `--permission-mode plan`. `--model`, `--no-session-persistence`,
  `--safe-mode`, `--no-chrome`, and empty MCP config flags are included only
  when local help advertises them. Dangerous permission bypass, unrestricted
  tools, auth, token, browser-control, deploy, publish, spend, message, and MCP
  auto-approval paths are never used.
- `codex-cli`: limited to discovered `codex exec` with `--sandbox read-only`
  and `--ask-for-approval never`. `--json`, `--ephemeral`,
  `--ignore-user-config`, `--color never`, and `--model` are included only when
  local help advertises them. Dangerous approval/sandbox bypass,
  danger-full-access sandbox, credential/auth/login/logout paths, MCP
  management, app-server, remote-control, mcp-server, exec-server, apply, cloud,
  update, browser-control, deploy, publish, spend, message, and web search paths
  are never used.
- `ollama`: one-shot `ollama run <model> <prompt>` (default model `llama3`).
- `noop`: echoes the task. Exists for tests and pipeline verification.

Missing executables produce unavailable capability snapshots and skipped
receipts. They do not crash normal adapter list, adapter inspect, receipt list,
or receipt inspect commands.

## Process runner

- Accepts argv lists only. Shell strings are rejected; the shell is never
  enabled.
- Configurable cwd and timeout. Timeouts and missing executables produce
  structured failed results, not exceptions.
- Full stdout/stderr is written to `.opencobalt/artifacts/<execution_id>/`
  and a 2000-character preview is stored inline.
- Environment variables are never dumped or logged.

## Receipts and verification

A `WorkReceipt` records: the task, selected runtime, route reason, risk
level, approval requirement, the runtime capability snapshot, the command
plan, the normalized invocation, the normalized adapter receipt, and the IDs
of all hashed output artifacts.

Event collection is invocation-local. Concurrent `run_task()` or replay calls
on one `ExecutionEngine` share the durable store and configured event sink, but
not the per-run event buffer used to build normalized receipts. One run's event
count, provenance references, plan, execution, and artifacts therefore cannot
be populated from another overlapping run.

`opencobalt receipts verify <id>` recomputes the SHA-256 of every referenced
artifact. Statuses: `unverified` (nothing attached, e.g. dry-run),
`verified` (all hashes match), `partial` (some match), `failed` (none match).

Hashing proves integrity, not safety: a verified receipt means the evidence
files have not changed since capture, not that the work was correct or
harmless. Artifacts may contain sensitive output and should be handled
carefully.

## Event stream

The engine emits structured events to `.opencobalt/events/execution.jsonl`
and to an optional in-process sink, so a future TUI/UI can render live state:

```
task.received  route.selected  plan.created  plan.replayed  policy.checked
execution.started  execution.output_captured
execution.succeeded  execution.failed
artifact.created  receipt.created
verification.passed  verification.failed
```

UI vocabulary this maps to: Task status planning / running / verifying /
done / failed. Receipt created / verified / failed. Risk green / yellow /
red / blocked. Mode dry-run / supervised / autonomous.

## Storage

Four tables in `.opencobalt/ledger.db`, created with
`CREATE TABLE IF NOT EXISTS` so existing databases are untouched:
`execution_plans`, `execution_results`, `execution_artifacts`,
`work_receipts`. JSON columns hold steps, argv, capability snapshots, and
artifact ID lists.

## Plan replay

Stored plans can be inspected and replayed:

```
opencobalt plans list                      stored plans, newest first
opencobalt plans inspect <plan_id>         steps, command, risk, approval needs
opencobalt plans execute <plan_id>         replay (dry-run by default)
opencobalt plans execute <plan_id> --execute --yes
```

Replay reuses the stored command plan exactly; it never re-routes or rebuilds
the command. Every replay creates a new plan (linked to the source by a
`plan.replayed` event) and a new receipt, and is re-gated by the same policy
as `opencobalt run`: dry-run always allowed, red risk needs `--execute --yes`,
black risk stays blocked with no override. Artifact hashes are re-verified
after an executed replay.

## Caffeinate (keep-awake)

Long runs can optionally hold the Mac awake:

```
opencobalt run "..." --execute --caffeinate
opencobalt plans execute <plan_id> --execute --caffeinate
```

On macOS this starts a scoped `caffeinate -dims -w <pid>` child for the
duration of the run; it is terminated when the run ends (including timeout or
failure) and the `-w <pid>` tie means it can never outlive OpenCobalt. It is
never enabled by default, does nothing on other platforms, only prevents
sleep during long runs, and has no effect on policy gates, approvals, or
model behavior.

## Known limitations (v0)

- One step per plan. Multi-step plans are modeled but not yet generated.
- Antigravity execution is limited to discovered `--print` mode. Browser
  automation, screenshots, subagent discovery, and Antigravity's private
  SQLite internals remain unknown and are not assumed.
- Verification is hash-only. Semantic verification (did the output answer
  the task) belongs to a later milestone.
- Cursor Runtime Adapter v0 is partial when `cursor agent --print --mode plan`
  is locally discovered. It is unavailable when Cursor is absent and untrusted
  when only unverifiable local surfaces are present.
- Cursor receipts verify captured stdout/stderr artifacts, not Cursor account
  state or semantic correctness. Cursor credentials, cookies, tokens, and
  project auth are never stored by OpenCobalt.
- Claude Code Runtime Adapter v0 is partial when local `claude --help` proves
  print mode with permission-mode plan. It is unavailable when `claude` is
  absent and discovery-only when safe headless invocation is not proven.
- Claude Code receipts verify captured stdout/stderr artifacts, not Claude
  account state, model correctness, or internal permission enforcement. Raw
  environment variables and credentials are never stored by OpenCobalt.
- Codex Runtime Adapter v0 is partial when local `codex --help` and
  `codex exec --help` prove exec mode with read-only sandbox and approval
  policy `never`. It is unavailable when `codex` is absent and discovery-only
  when safe headless invocation is not proven.
- Codex receipts verify captured stdout/stderr artifacts, not Codex account
  state, model correctness, or internal permission enforcement. Raw environment
  variables and credentials are never stored by OpenCobalt.
