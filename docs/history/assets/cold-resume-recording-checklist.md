# Cold Resume Recording Checklist

Agents come and go. Models change. Sessions die. OpenCobalt remembers.

OpenCobalt converts ephemeral agent work into durable mission intelligence.

This demo does not call a live model, launch an agent, or grant authority. It demonstrates local durable memory, verification, and handoff.

Use this checklist before recording a 60 to 120 second cold-resume demo.

## Before Recording

- Use a clean terminal window with a readable zoom level.
- Hide the shell prompt path, username, host name, and account names.
- Disable notifications and screen overlays.
- Close unrelated terminals, browser windows, editors, and cloud consoles.
- Start from a clean repo state.
- Do not show shell history.
- Do not show environment variables, `.env` files, credential files, keychains,
  session files, cookies, API keys, tokens, private keys, seed phrases, or
  wallets.
- Do not show raw old-agent reports or raw transcripts.
- Do not show private repo details beyond `moderqtor/OpenCobalt`.

## Commands To Record

Main recording:

```bash
.venv/bin/opencobalt demo cold-resume --target codex-cli
```

Optional proof commands, using the mission id printed by the demo:

```bash
.venv/bin/opencobalt continue MISSION_ID
.venv/bin/opencobalt handoff MISSION_ID --to codex-cli
```

## On-Screen Beats

- Show the command before running it.
- Show the north star line.
- Show `Created mission: mis-...`.
- Show `Attached extraction: mex-...`.
- Show `Verified extraction: mver-...`.
- Show the safety checks.
- Show the `opencobalt continue MISSION_ID` command.
- Show the `opencobalt handoff MISSION_ID --to codex-cli` command.
- Show verifier warnings remain visible.

## Do Not Claim

- Do not claim OpenCobalt trains models.
- Do not claim OpenCobalt improves model weights.
- Do not claim the demo calls a live model.
- Do not claim the demo launches Codex, Claude, Cursor, or another runtime.
- Do not claim live multi-agent execution.
- Do not imply that handoff packets grant authority.
- Do not imply mission state is unquestionable truth.

## Safe Closing Line

```text
OpenCobalt converts ephemeral agent work into durable mission intelligence.
```

## Post-Recording Review

- Rewatch once with audio off and confirm no private local data is visible.
- Rewatch once with audio on and confirm the narration does not overclaim.
- Confirm no token-shaped strings, account names, local paths, or unrelated
  history are visible.
- Confirm the demo is framed as local, deterministic, non-authorizing mission
  memory, verification, and handoff.
