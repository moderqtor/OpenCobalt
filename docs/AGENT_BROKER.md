# Agent Broker v0

Agent Broker v0 is OpenCobalt's first durable supervisor for external coding-agent sessions.
It is deliberately narrower than a general autonomous Mission runner.

## Why it exists

External coding sessions are useful but ephemeral from OpenCobalt's point of view. The
broker gives OpenCobalt its own durable record of:

- the user objective
- the authoritative repository and starting branch/head
- the staged workspace used by the worker
- the external provider thread id
- each prompt/response turn
- the receipt for every attempted runtime turn
- local stop state

The provider thread is useful context. It is not OpenCobalt's source of truth.

## Codex v0 backend

The first backend uses the official `openai-codex` Python SDK. The SDK supports durable
threads that can be started and resumed later. OpenCobalt does not call that SDK from
ordinary application code. Instead:

```text
AgentBroker
  -> ExecutionEngine
    -> CodexSdkBrokerAdapter
      -> python -m opencobalt.agent_broker.worker
        -> official openai_codex SDK
```

This preserves the repository doctrine that external runtime task execution crosses
`ExecutionEngine` and leaves a WorkReceipt.

The worker uses:

- `Sandbox.workspace_write`
- `ApprovalMode.deny_all`
- the OpenCobalt staged workspace as `cwd`

The worker is instructed not to push, merge, deploy, publish, spend, send external
messages, access secrets/auth state, or expand scope. Sandbox escalation is denied.
This is staged repository containment, not a claim of full host isolation.

## Staged workspace

A new broker session creates an OpenCobalt staged workspace under:

```text
.opencobalt/agent-broker-workspaces/
```

For Git repositories this uses the existing staging controller's detached worktree
path. Provider writes therefore do not directly change the authoritative checkout.
Promotion is intentionally not part of Broker v0. Existing staging/changeset/approval
primitives should own that later rather than the broker inventing another apply path.

## Durable state

Broker records are additive tables in the shared `.opencobalt/ledger.db`:

- `agent_broker_sessions`
- `agent_broker_turns`

A session stores OpenCobalt's broker id separately from the provider thread id. This
allows provider sessions to disappear or change without making provider state the
primary record.

## CLI

Install the optional backend dependency:

```bash
pip install -e '.[codex]'
```

or with the project's package manager equivalent.

Then:

```bash
opencobalt-broker start "inspect the failing tests and fix them" --repo . --execute
opencobalt-broker status
opencobalt-broker continue AGENT_SESSION_ID "review the diff and run focused tests" --execute
opencobalt-broker status AGENT_SESSION_ID --json
opencobalt-broker stop AGENT_SESSION_ID
```

Execution is dry-run by default. `--execute` is required to invoke Codex. `--yes` is
only an OpenCobalt policy-gate approval for red-risk tasks; it does not grant the Codex
worker broader authority or disable its sandbox/escalation boundary.

`stop` is local by default. `--archive-provider --execute` also asks Codex to archive
its persisted provider thread through the same receipt-backed execution path.

## Not yet implemented

Broker v0 does **not** yet provide:

- a GitHub/Slack relay that lets a remote controller enqueue follow-up prompts
- background polling or a daemon
- automatic evaluation of the previous turn and self-generated follow-up prompts
- cross-provider handoff
- automatic changeset promotion
- push/merge/deploy authority
- a normal-user UI

The next useful increment is a narrow relay/control channel so ChatGPT or another
controller can write a bounded instruction into a shared queue, the local broker can
run it, and the result/receipt can be written back for the controller to inspect.
