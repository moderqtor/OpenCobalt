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
- deduplicated relay command/result events when the GitHub relay is enabled

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
- an explicit decline handler for any SDK server request that still asks for more authority

The explicit handler is defense in depth. Current Codex SDK versions map `deny_all` to an
approval policy of `never`, but OpenCobalt also replaces the low-level request handler with
a fail-closed decline callback before a thread or turn is started. If the SDK stops exposing
the expected handler slot, the worker refuses to run instead of silently weakening this
boundary.

The worker is instructed not to push, merge, deploy, publish, spend, send external
messages, access secrets/auth state, or expand scope. This is staged repository containment,
not a claim of full host isolation.

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
- `agent_broker_relay_events`

A session stores OpenCobalt's broker id separately from the provider thread id. This
allows provider sessions to disappear or change without making provider state the
primary record.

Relay events persist the source comment and command id before execution. A GitHub result
write failure therefore leaves a `result_pending` record that can be retried without
executing the agent turn again.

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

## GitHub controller relay

The relay removes the human copy/paste step between a remote controller and the local
broker while keeping execution local.

A user deliberately starts one foreground relay process, for example:

```bash
opencobalt-broker relay \
  --github-repo moderqtor/OpenCobalt \
  --issue 42 \
  --author moderqtor \
  --local-repo ~/dev/OpenCobalt \
  --execute-agent \
  --allow-github-comments
```

The relay requires the GitHub CLI (`gh`) to already be authenticated. OpenCobalt invokes
`gh api`; it does not ask for, print, or persist a GitHub token. The explicit
`--allow-github-comments` flag grants only the comment read/write channel used by this
foreground process. It does not grant git push, merge, release, deploy, or repository
mutation authority.

The configured issue number may also be a pull request because GitHub exposes ordinary PR
conversation comments through the issue-comment API.

Only comments that satisfy all of these conditions can become commands:

1. the comment is on the single configured repository and issue/PR;
2. its author login exactly matches `--author`;
3. it includes the v1 command marker;
4. it contains a valid bounded JSON command;
5. its `command_id` has not already been processed on that relay channel.

Example controller message:

```text
<!-- opencobalt-agent-command:v1 -->
```json
{"action":"continue","command_id":"cmd-...","prompt":"Review the failing test and fix only that regression.","session_id":"agent-..."}
```
```

Supported actions are `start`, `continue`, `status`, and `stop`. Remote commands cannot
select a local filesystem path. `start` is always bound to the `--local-repo` chosen when
the user launched the relay. Model selection is likewise fixed by the local relay process
when configured.

Results are posted with a separate v1 result marker and include the broker session id,
provider thread id when available, execution status, and WorkReceipt id. Response text is
redacted with OpenCobalt's existing text redactor, local home paths are replaced, and the
public result is bounded to 8,000 characters. The full local turn remains in the ledger.

**Channel visibility matters.** A relay result comment has the visibility of the GitHub
issue or PR that carries it. Do not bind private or sensitive work to a public relay
channel. The relay does not make a public GitHub thread private.

The process polls in the foreground and stops on Ctrl+C. `--once` is available for one
poll cycle. It is intentionally not installed as a background service in v0.

## What this enables

While the local relay is running, a controller that can read and write the configured
GitHub thread can:

1. post a `start` command;
2. wait for the receipt-linked result comment;
3. inspect that result;
4. post another `continue` command against the same durable Codex thread;
5. repeat without the user copying prompts or outputs between tools.

The relay is transport, not intelligence. The controller still decides whether another
turn is warranted. OpenCobalt records and constrains each local turn.

## Not yet implemented

Broker v0 does **not** yet provide:

- automatic evaluation of the previous turn and self-generated follow-up prompts
- cross-provider handoff
- automatic changeset promotion
- push/merge/deploy authority
- a normal-user UI
- an installed background daemon/service
- a private hosted relay transport

A later Mission runner can build on this broker rather than inventing another provider
session model. A future private relay should replace public issue comments for sensitive
work instead of weakening the current visibility warning.
