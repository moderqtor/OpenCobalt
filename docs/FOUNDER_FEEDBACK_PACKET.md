# OpenCobalt Founder Feedback Packet

Agents come and go. Models change. Sessions die. OpenCobalt remembers.

OpenCobalt is local-first infrastructure that turns ephemeral AI-agent work into durable, verified mission memory.

Plain English: OpenCobalt lets AI coding sessions remember what happened, so a fresh agent can pick up where the last one stopped.

OpenCobalt does not train models or replace coding agents. It operates at inference time as a local mission memory and handoff layer: extracting structured state from agent reports, verifying it against source output, and generating target-specific continuation packets for future agents.

This is an early feedback packet for technical founders, AI startup operators, developer-tool people, and early advisor-type readers. It is not a fundraising deck.

## What OpenCobalt is

OpenCobalt is a local-first mission memory layer for AI coding work. It turns a finished agent report into structured durable mission state, records verification metadata, and renders continuation packets for the next agent session.

The useful unit is durable mission memory: what happened, what was verified, what is still risky, what files changed, and what a future agent should inspect first. Mission state is continuity context, not unquestionable truth.

## The problem

AI coding agents are useful but session-bound. The chat history, local reasoning, tool outputs, and "what mattered" often disappear when the session ends.

Handoffs are usually manual, lossy, and hard to verify. A new agent may start with stale context, missing warnings, or no clear boundary between evidence and instructions.

Teams increasingly need memory, provenance, and authority boundaries around AI work. It is not enough for a coding agent to produce output; the work needs durable context that future sessions can inspect without granting hidden authority.

## The wedge

The narrow wedge is cold resume from an old agent report.

OpenCobalt can close a completed session into durable mission state, verify the extracted state against the source report, and generate a target-specific handoff for Codex, Claude Code, Cursor-style tools, or a generic agent.

The current local loop is:

```text
real agent report
-> opencobalt missions close-session ... --verify --handoff-to codex-cli
-> extraction
-> verification
-> durable mission memory
-> cold continue
-> Codex handoff
-> fresh agent can resume
```

## What works today

- Deterministic local CLI.
- SQLite mission ledger.
- Extraction from real agent reports.
- Verification records attached to mission memory.
- One-shot `close-session` workflow.
- Compact `opencobalt continue MISSION_ID` output.
- Target-specific handoff packets.
- Public safety check.
- Current post-merge suite: `1126 passed, 1 warning`.

## Demo

Run the deterministic cold-resume demo:

```bash
opencobalt demo cold-resume --target codex-cli
```

Use the real close-session workflow on a finished agent report:

```bash
opencobalt missions close-session MISSION_ID --file report.txt --verify --handoff-to codex-cli
```

What to notice:

- Mission id: `mis-...`.
- Extraction id: `mex-...`.
- Verification id: `mver-...`.
- Warnings stay visible.
- The output prints the `opencobalt continue MISSION_ID` command.
- The output prints or renders the target handoff packet.
- No live model calls are made.
- No runtime or agent is launched.
- No authority is granted to push, merge, deploy, publish, spend, message, touch secrets, or perform irreversible actions.

## What this proves

- Agent reports can be converted into durable mission memory.
- Fresh sessions can resume from structured state instead of raw chat history.
- State can carry verification status, verifier warnings, confidence, and safety boundaries.
- Handoff can be target-specific while preserving the same underlying mission memory.

## What this does not prove yet

- It is not external user validation.
- It is not a hosted product.
- It is not a team workflow yet.
- It is not live LLM extraction.
- It is not autonomous multi-agent execution.
- It is not model training or model-weight improvement.
- It does not prove every extracted claim is true.

## Why I am asking for feedback

I am not fundraising right now.

I want to pressure-test whether this is a real developer pain. The question is whether cross-session AI-agent memory is painful enough that a technical user would install a local CLI and use it weekly.

I want to know what would make this worth installing or using weekly. I am especially interested in whether the cold-resume wedge is sharp enough.

## Questions for feedback

1. Is cross-session AI-agent memory a real pain in your workflow?
2. Would you install a local CLI to get durable mission handoff?
3. What part of the demo feels useful?
4. What part feels fake or unnecessary?
5. Would verification or provenance matter to you?
6. What would make this a weekly-use tool?
7. Should this stay local-first or become team/cloud-first?
8. Who has this pain most acutely?

## Optional outbound message

```text
I am building OpenCobalt, a local-first mission memory layer for AI coding agents.

The narrow wedge is cold resume: it can take a finished agent report, extract durable mission state, verify it, and generate a handoff so a fresh Codex/Claude-style session can continue without the original chat history.

I am not fundraising right now. I am looking for blunt feedback from people who understand AI/dev-tool workflows: is this a real pain, and what would make it useful enough to install?

Repo/demo packet: [link]
```

## Links

- [README](../README.md)
- [Cold resume demo guide](COLD_RESUME_DEMO.md)
- [Cold resume video script](COLD_RESUME_VIDEO_SCRIPT.md)
- [Expected output guide](assets/cold-resume-demo-output.md)
- [Sanitized terminal transcript](assets/cold-resume-demo-transcript.txt)
- [Recording checklist](assets/cold-resume-recording-checklist.md)
