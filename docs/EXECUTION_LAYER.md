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

## Architecture

All code lives in `src/opencobalt/execution/`:

| Module | Responsibility |
|--------|----------------|
| `models.py` | `ExecutionPlan`, `ExecutionStep`, `ExecutionResult`, `ExecutionArtifact`, `WorkReceipt` (Pydantic) |
| `policy.py` | Deterministic risk classification and the execution gate |
| `adapters.py` | `RuntimeAdapter` protocol plus `google-antigravity`, `ollama`, `noop` adapters |
| `runner.py` | Safe subprocess runner (argv lists, no shell, timeouts, output spill) |
| `artifacts.py` | Streaming SHA-256 hashing, attach, verify |
| `store.py` | SQLite persistence in `.opencobalt/ledger.db` |
| `engine.py` | `ExecutionEngine`: the full slice plus structured event emission |

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

An adapter never executes anything. It detects the runtime, reports a
capability snapshot, and builds a default-safe argv:

- `google-antigravity`: limited to the discovered non-interactive `--print`
  mode. `--model` and `--sandbox` are included only when discovered in local
  `agy --help`. `--dangerously-skip-permissions` is never added by default;
  the explicit unsafe override emits a RuntimeWarning and a policy event.
  If `--print` was not discovered, command construction fails cleanly.
- `ollama`: one-shot `ollama run <model> <prompt>` (default model `llama3`).
- `noop`: echoes the task. Exists for tests and pipeline verification.

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
level, approval requirement, the runtime capability snapshot, the exact
command argv, and the IDs of all hashed output artifacts.

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
