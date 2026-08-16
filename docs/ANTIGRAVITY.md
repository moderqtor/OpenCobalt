# Google Antigravity CLI

## What changed

OpenCobalt now treats Google Antigravity CLI as the canonical Google agent runtime.
The integration ID is `google-antigravity` and the local command is `agy`.

Gemini CLI integration is deprecated. Existing Gemini CLI aliases remain supported
temporarily and resolve to `google-antigravity` with a deprecation warning. Gemini
remains a valid model-family name, for example `gemini-pro` or `gemini-flash`.

## Why Gemini CLI is legacy

Gemini CLI described one Google CLI product. Antigravity is modeled as an agent
runtime: it can coordinate local work through terminal, editor, browser, plugins, and
artifacts where those capabilities are discoverable from the installed runtime.
OpenCobalt must route to the runtime, not conflate the runtime with a model family.

## Canonical identity

| Field | Value |
|-------|-------|
| Canonical config ID | `google-antigravity` |
| Display name | Google Antigravity CLI |
| Command | `agy` |
| Vendor | Google |
| Kind | `agent_runtime` |
| Status | `primary` |

Legacy aliases:

- `gemini-cli`
- `gemini_cli`
- `google-gemini-cli`
- `legacy-gemini-cli`
- `antigravity-cli`

## Runtime discovery

Run:

```bash
opencobalt doctor antigravity
```

OpenCobalt checks:

1. Whether `agy` is on PATH
2. The resolved `agy` path
3. Whether `agy --version` works
4. Whether `agy --help` works
5. Evidence of non-interactive mode
6. Evidence of model selection flags
7. Evidence of plugin or extension support
8. Evidence of sandboxed terminal execution
9. Evidence of unsafe permission bypass flags

The diagnostic records a verification receipt in the local ledger when possible.
Missing `agy` is reported cleanly and does not fail the whole doctor command.

## Known capabilities

OpenCobalt statically models Antigravity as:

- interactive CLI
- agent runtime
- executive-tier runtime for multi-agent, browser, workspace, and artifact-heavy work

When local help output exposes flags or subcommands, OpenCobalt marks those fields as
`runtime_discovered` and stores the evidence string. For example, a local `agy --help`
that contains `--print`, `--model`, `plugin`, or `--sandbox` records those exact
features as discovered.

Known dynamically discoverable help evidence:

- `--print`: marks `non_interactive_print` supported. OpenCobalt can build a pure
  argv form like `agy --print "hello"` for non-interactive tasks.
- `--model`: marks `model_selection` supported. OpenCobalt can build a pure argv
  form like `agy --model <model> --print "hello"` when model selection is needed.
- `--output-format`: marks `json_output` supported. `stream-json` in help also
  marks `stream_json_output`.
- `--json-schema`: marks structured output support.
- `--effort`: marks `reasoning_effort` (`low`, `medium`, `high`).
- `--sandbox`: marks `sandbox_mode` supported. This is safety enhancing and should
  be preferred for untrusted or worker-tier work if such work is routed to `agy`.
- `--dangerously-skip-permissions`: marks `unsafe_skip_permissions` supported but
  red risk and not allowed by default.
- `models` subcommand: marks authenticated catalog discovery via
  `agy --output-format json models`. The global `--output-format` flag must come
  before the subcommand.

## Personal AI Chat boundary

Ordinary Chat does not use the generic repository-cwd Antigravity adapter.
Chat admission requires discovered JSON print and `--sandbox` support. Each
invocation uses an atomically created, unpredictable private mode-0700 directory
directly under the OS temporary root,
outside the attached repository, with `--sandbox`, JSON output, and never
`--dangerously-skip-permissions`. The directory is removed after the bounded
invocation on a best-effort basis. This reduces repository discovery and
mutation exposure; it is not an OpenCobalt-provided OS sandbox. If either the
managed external workspace or Antigravity's sandbox flag cannot be proven,
`ExecutionEngine` does not classify the invocation as answer-only isolated.
Headless permission prompts are not auto-approved.

Authenticated models are discovered from the JSON catalog. Identifier suffixes
such as `-high` or names such as `opus` are routing heuristics, not live
quality or price calibration. Local-only Chat excludes Antigravity before any
`agy` invocation, including model discovery.

Research retrieval is owned by OpenCobalt: candidate URLs are fetched with a
bounded HTTPS GET through `ExecutionEngine`. Cited claims are linked to
retrieved evidence IDs; linkage is not a factual-truth proof.

## Unknown capabilities

OpenCobalt does not guess. These fields remain `unknown` unless local runtime evidence
is discovered:

- multi-agent orchestration details
- artifact generation details
- browser automation or screenshot command-line syntax
- terminal execution details beyond discovered help output
- editor context
- SQLite conversation database schema from `agy` 1.0.4
- subagent discovery or query protocol
- skills, hooks, and subagents
- artifact storage locations

## Safety notes

Agent runtimes with terminal, browser, and file access are powerful but risky.
OpenCobalt adds visibility, receipts, deterministic routing, policy metadata, and
approval boundaries. Antigravity defaults to yellow or red risk depending on task
shape and should not be silently treated as a green-lane runtime for autonomous work.

Do not use Antigravity for credential handling, destructive filesystem operations,
deployment, package publishing, browser login automation, or external network
automation without explicit approval.

OpenCobalt must never pass `--dangerously-skip-permissions` by default. That flag
auto-approves permission requests and is treated as unsafe even when local help
advertises it. Any code path that exposes it must require an explicit unsafe override
and produce a warning or policy event.

For untrusted or worker-tier tasks routed to Antigravity, prefer `--sandbox` when
local help exposes it. Tasks involving credentials, `.env` files, tokens, SSH keys,
browser profiles, package publishing, deployment, or environment configuration require
explicit approval before routing to `agy`.

## Artifact ingestion roadmap

OpenCobalt does not depend on Antigravity private storage paths. The current foundation
supports local work-artifact records with:

- `artifact_id`
- `session_id`
- `source_runtime`
- `artifact_type`
- `path`
- `sha256`
- `created_at`
- `summary`

Supported artifact types are `plan`, `task_list`, `screenshot`, `browser_recording`,
`diff`, `test_output`, `log`, `report`, and `unknown`.

These records are implemented by Receipt-Backed Execution v0
(see `docs/EXECUTION_LAYER.md` and `docs/ARTIFACT_RECEIPTS.md`):

```bash
opencobalt artifacts list
opencobalt artifacts attach <path> --source google-antigravity --type report
opencobalt artifacts verify <id>
```

## Execution support

`opencobalt run` can plan and, when explicitly approved, execute one-shot
Antigravity tasks through the discovered non-interactive `--print` mode:

```bash
opencobalt run "summarize docs/ANTIGRAVITY.md" --runtime google-antigravity --dry-run
opencobalt run "hello" --runtime google-antigravity --execute --sandbox
```

Execution is policy-gated (see `docs/EXECUTION_LAYER.md`). The command argv
is built from discovered capabilities only: `--model` and `--sandbox` are
included when local help advertises them, and execution fails cleanly when
`--print` was not discovered. Browser automation, screenshot capture,
subagent discovery, and Antigravity's private SQLite schema remain unknown
and are never assumed. `--dangerously-skip-permissions` is forbidden by
default; the unsafe override warns and records a policy event.

## Agent Broker integration

`opencobalt-broker` supports `google-antigravity` as a first-class resumable backend:

```bash
opencobalt-broker start "inspect codebase" --repo . --runtime google-antigravity --execute
opencobalt-broker continue AGENT_SESSION_ID "implement requested changes" --execute
opencobalt-broker stop AGENT_SESSION_ID
```

- **Staged workspace containment**: Subprocess execution occurs inside OpenCobalt detached git worktrees under `.opencobalt/agent-broker-workspaces/`.
- **Native conversation resumption**: Resuming a session passes `--conversation <conversation_id>` to `agy`, continuing the exact same provider context across multiple turns.
- **Durable WorkReceipts**: Every turn records a cryptographic receipt in `.opencobalt/ledger.db`.
- **Truthful capability reporting**: Server-side conversation archiving is reported as `status="unsupported"` rather than inventing non-existent functionality.

## Examples

Route browser validation to Antigravity:

```bash
opencobalt route "validate the dashboard in a browser and record screenshots"
```

Inspect local runtime support:

```bash
opencobalt doctor antigravity
```

Use the canonical config ID in docs or local notes:

```text
runtime = google-antigravity
runtime_command = agy
model_policy = high_reasoning_or_browser_capable
```
