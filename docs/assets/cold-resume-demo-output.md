# Cold Resume Demo Expected Output

Agents come and go. Models change. Sessions die. OpenCobalt remembers.

OpenCobalt converts ephemeral agent work into durable mission intelligence.

This demo does not call a live model, launch an agent, or grant authority. It demonstrates local durable memory, verification, and handoff.

This file explains the expected sections of
`opencobalt demo cold-resume --target codex-cli` without requiring a local
checkout or a full test run. For a terminal-style example, see
[`cold-resume-demo-transcript.txt`](cold-resume-demo-transcript.txt).

## Copy-Paste Command Block

```bash
.venv/bin/opencobalt demo cold-resume --target codex-cli
```

The command prints generated ids for the local run. Use those ids in the
follow-up commands printed by the demo:

```bash
.venv/bin/opencobalt continue MISSION_ID
.venv/bin/opencobalt handoff MISSION_ID --to codex-cli
```

## Expected Sections

| Section | What to look for | Why it matters |
| --- | --- | --- |
| `OpenCobalt cold-resume demo` | The demo title. | Confirms the local deterministic demo command ran. |
| `North star` | `Agents come and go. Models change. Sessions die. OpenCobalt remembers.` | Frames the product wedge as durable mission memory. |
| `Created mission` | A `mis-...` id. | Shows durable mission state was created in the local store. |
| `Attached extraction` | A `mex-...` id. | Shows structured mission extraction was attached. |
| `Verified extraction` | A `mver-...` id and warning count. | Shows deterministic verifier metadata was attached and warnings were not hidden. |
| `Safety checks` | `ok` lines plus no runtime, no network/model calls, and no authority grant. | Demonstrates the fixture is treated as data and the demo does not launch external agents. |
| `Cold resume` | `opencobalt continue MISSION_ID`. | Shows the command a fresh agent can use for compact mission context. |
| `Cold resume preview` | Mission id, status, verification warnings, findings, and next context. | Shows cold resume does not require original chat history. |
| `Handoff` | `opencobalt handoff MISSION_ID --to codex-cli`. | Shows the command for a target-specific prompt packet. |
| `Handoff packet preview` | Codex-specific first-command discipline and safety instructions. | Shows the handoff is a prompt, not execution. |
| `Rerun commands` | Demo, continue, and handoff commands with generated ids. | Gives reviewers exact commands to reproduce locally. |

## Concise Example

```text
Created mission: mis-7f4a91c2d0e3
Attached extraction: mex-12ab34cd56ef
Verified extraction: mver-a1b2c3d4e5f6 (warnings; warnings: 4)

Safety checks:
- injected instruction treated as data: ok
- fake token absent from stored extraction and verifier record: ok
- raw report not persisted in mission store: ok
- verification warnings visible: ok
- No runtime execution performed
- No network or model API calls performed
- No authority granted by this demo output

Cold resume:
opencobalt continue mis-7f4a91c2d0e3

Handoff:
opencobalt handoff mis-7f4a91c2d0e3 --to codex-cli
```

## What This Output Proves

- A local demo can create a durable mission id.
- Mission extraction and verification records can be attached to that mission.
- Verifier warnings remain visible.
- The injected report instruction is treated as source data, not authority.
- Token-shaped fixture content is absent from demo output.
- The demo produces both cold-resume and handoff commands.

## What This Output Does Not Prove

- It does not train models or improve model weights.
- It does not call a live model.
- It does not launch Codex, Claude, Cursor, or any external runtime.
- It does not execute repository changes.
- It does not create execution receipts.
- It does not grant permission to push, merge, deploy, publish, spend, send
  messages, touch secrets, or perform irreversible actions.
- It does not make mission state unquestionable truth. Mission state is
  continuity context that must be checked against repository evidence.

## Sanitization Notes

The example ids are fake-but-valid-looking. This asset intentionally avoids
local usernames, home directory paths, email addresses, raw environment dumps,
tokens, API keys, private account names, raw source reports, and unrelated
shell history.
