# Cold Resume Video Script v0

> Historical. Recording notes for an implemented CLI demo. Not current product
> identity. See [README.md](../../README.md).

This demo does not call a live model, launch an agent, or grant authority.

Use this script for a 60 to 120 second screen recording of the deterministic
local cold-resume demo. The recording should not claim live model execution,
agent launch, or training-time model improvements.


Companion assets:

- [Sanitized terminal transcript](assets/cold-resume-demo-transcript.txt)
- [Expected output guide](assets/cold-resume-demo-output.md)
- [Recording checklist](assets/cold-resume-recording-checklist.md)

## Positioning

Founder-facing one-liner:

```text
OpenCobalt is local-first infrastructure that turns ephemeral AI-agent work into durable, verified mission memory.
```

Normal-user-facing one-liner:

```text
OpenCobalt lets AI coding sessions remember what happened, so a fresh agent can pick up where the last one stopped.
```

Technical-founder explanation:

```text
OpenCobalt does not train models or replace coding agents. It operates at inference-time as a local mission memory and handoff layer: extracting structured state from agent reports, verifying it against source output, and generating target-specific continuation packets for future agents.
```

## Recording Setup

Record from a clean terminal with a readable font and a prompt that does not
show local account names, private paths, private repo details, cloud account
names, tokens, or unrelated shell history.

Recommended setup:

```bash
clear
.venv/bin/opencobalt status
```

Do not show:

- raw environment dumps such as `env`, `printenv`, or shell startup files
- credential stores, API keys, tokens, cookies, session files, private keys,
  seed phrases, wallets, or auth files
- unrelated terminal history
- private issue trackers, private repo URLs, or private account names
- raw old-agent report text containing injected instructions or token-shaped
  fixture strings

## Exact Commands

Run the main demo:

```bash
.venv/bin/opencobalt demo cold-resume --target codex-cli
```

Then copy the generated mission id from the output and use it for the optional
proof commands:

```bash
.venv/bin/opencobalt continue MISSION_ID
.venv/bin/opencobalt handoff MISSION_ID --to codex-cli
```

For a shorter recording, show the `Rerun commands` section printed by the demo
instead of running the proof commands.

## 60-Second Version

| Time | Screen beat | Narration |
| --- | --- | --- |
| 0:00-0:10 | Show clean terminal. | "AI coding agents are powerful, but their sessions die. Context fragments across tools." |
| 0:10-0:20 | Show the command before running it. | "OpenCobalt is the durable mission memory layer. Agents come and go. Models change. Sessions die. OpenCobalt remembers." |
| 0:20-0:40 | Run `.venv/bin/opencobalt demo cold-resume --target codex-cli`. | "This creates a local mission, ingests a sanitized old-agent report, extracts mission state, verifies it, and prepares cold-resume context." |
| 0:40-0:55 | Point at mission id, extraction id, verification id, safety checks, continue command, and handoff command. | "The proof is durable state: mission id, extraction id, verification id, continue output, and a Codex-targeted handoff packet." |
| 0:55-1:00 | Show safety lines. | "No live model call, no runtime execution, no authority grant. This is local cold resume." |

Close with:

```text
OpenCobalt converts ephemeral agent work into durable mission intelligence.
```

## 120-Second Version

| Time | Screen beat | Narration |
| --- | --- | --- |
| 0:00-0:15 | Clean terminal and short problem statement. | "AI coding sessions are useful but fragile. When a session dies, the next agent often starts without the real operating context." |
| 0:15-0:30 | Show the command. | "OpenCobalt records mission memory outside the chat session, so future agents can resume from durable context instead of guessing from scratch." |
| 0:30-1:00 | Run `.venv/bin/opencobalt demo cold-resume --target codex-cli`. | "This is deterministic and local. It creates a mission, ingests a sanitized old-agent report, attaches extraction state, and verifies that extraction against source output." |
| 1:00-1:25 | Highlight `Created mission`, `Attached extraction`, and `Verified extraction`. | "These ids are the receipts for the demo: a mission record, an extraction record, and a verifier record." |
| 1:25-1:40 | Show `Cold resume preview` and `opencobalt continue MISSION_ID`. | "A fresh agent can start with compact mission context without needing the original chat history." |
| 1:40-1:50 | Show `Handoff packet preview` and `opencobalt handoff MISSION_ID --to codex-cli`. | "For coding agents, OpenCobalt generates a copy-paste handoff packet with warnings, next actions, safety boundaries, and first commands." |
| 1:50-1:58 | Show safety checks. | "The injected instruction stays data. Token-shaped content is absent. The demo does not execute agents or call a model." |
| 1:58-2:00 | Hold on command output. | "OpenCobalt turns ephemeral agent work into durable mission intelligence." |

## What To Show

- The command `.venv/bin/opencobalt demo cold-resume --target codex-cli`.
- `Created mission: mis-...`.
- `Attached extraction: mex-...`.
- `Verified extraction: mver-...`.
- `Safety checks`, especially injected instruction handling, fake-token absence,
  raw-report non-persistence, visible verifier warnings, no runtime execution,
  no network or model API calls, and no authority grant.
- The printed `opencobalt continue MISSION_ID` command.
- The printed `opencobalt handoff MISSION_ID --to codex-cli` command.
- The preview text showing a future agent can resume from durable mission
  memory.

## What Not To Show

- Raw source reports, transcripts, or logs that might contain instructions,
  secrets, private paths, or unrelated data.
- Environment variables or credential files.
- Private repository metadata not needed for the demo.
- Browser sessions, cloud consoles, or external runtime windows.
- Any UI that implies OpenCobalt launched Codex, Claude, Cursor, or another
  agent during this demo.

## What This Proves

- OpenCobalt can create durable local mission state from a cold terminal demo.
- A sanitized old-agent report can become structured mission intelligence.
- Extraction and verification records are attached as durable ids.
- Warnings remain visible in continue and handoff previews.
- A future agent can receive compact continuation context or a target-specific
  handoff packet.
- Injected report instructions are treated as data, not authority.
- Token-shaped fixture content is not printed by the demo.

## What This Does Not Prove

- It does not prove live model quality.
- It does not train or improve model weights.
- It does not launch Codex, Claude, Cursor, or any runtime.
- It does not execute repository changes.
- It does not create execution receipts.
- It does not grant permission to push, merge, deploy, publish, spend, send
  messages, touch secrets, or perform irreversible actions.
- It does not prove every extracted claim is true. Mission state is useful
  continuity context, not unquestionable truth.

## Accuracy Guardrails

Use these lines if asked what is happening:

```text
This is a deterministic local demo of mission memory, verification, continue output, and handoff packets.
```

```text
The demo shows inference-time continuity infrastructure. It does not train models, call a live model, or launch an external coding agent.
```

```text
Handoff packets are prompts, not authority grants. A receiving agent still needs to inspect the repo, review warnings, and get explicit permission for irreversible actions.
```
