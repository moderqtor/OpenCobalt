# Cold Resume Demo v0

Agents come and go. Models change. Sessions die. OpenCobalt remembers.

`opencobalt demo cold-resume` is a deterministic local demo of the mission
memory wedge:

```text
old agent report
-> mission extraction
-> verification
-> handoff packet
-> fresh agent can resume from durable mission memory
```

The demo creates a real local mission in the configured OpenCobalt store,
ingests a built-in old-agent report fixture, verifies the extraction against
that report, and prints compact cold-resume and handoff previews. It does not
launch Codex, Claude, Cursor, or any other runtime.

For a polished 60 to 120 second screen-recording outline, see
[Cold Resume Video Script v0](COLD_RESUME_VIDEO_SCRIPT.md).

Repo-safe demo assets:

- [Sanitized terminal transcript](assets/cold-resume-demo-transcript.txt)
- [Expected output guide](assets/cold-resume-demo-output.md)
- [Recording checklist](assets/cold-resume-recording-checklist.md)

The assets use fake-but-valid-looking ids and avoid local private data. They
are explanatory examples, not receipts from a live run.

## 60-second script

Run:

```bash
.venv/bin/opencobalt demo cold-resume
```

Optional target-specific variants:

```bash
.venv/bin/opencobalt demo cold-resume --target generic
.venv/bin/opencobalt demo cold-resume --target codex-cli
.venv/bin/opencobalt demo cold-resume --target claude-code
.venv/bin/opencobalt demo cold-resume --target cursor
```

Expected output sections:

- `OpenCobalt cold-resume demo`
- `North star`
- `Created mission: mis-...`
- `Attached extraction: mex-...`
- `Verified extraction: mver-...`
- `Safety checks`
- `Cold resume`
- `Cold resume preview`
- `Handoff`
- `Handoff packet preview`
- `Rerun commands`

The exact ids are generated per run. The rerun commands show how to inspect
the created mission:

```bash
.venv/bin/opencobalt continue MISSION_ID
.venv/bin/opencobalt handoff MISSION_ID --to TARGET
```

## What the demo proves

- A mission can be created from a cold terminal session.
- A prior agent-style report can become durable structured mission state.
- Extraction and verification are attached as `mex-...` and `mver-...`
  records in the local mission store.
- Verifier warnings remain visible in cold-resume and handoff previews.
- The built-in report's injected instruction is treated as source data, not
  as authority.
- Token-shaped fixture content is redacted and is not emitted by the demo.
- Raw source report text is not persisted in the mission store.
- A fresh agent can receive either `opencobalt continue MISSION_ID` output or a
  target-specific `opencobalt handoff MISSION_ID --to TARGET` packet.

## What it does not prove

- It does not make live model calls.
- It does not execute agents or runtime adapters.
- It does not contact Codex, Claude, Cursor, browsers, cloud services, or
  remote control surfaces.
- It does not create execution receipts.
- It does not grant approval or authority to push, merge, deploy, publish,
  spend, message, touch secrets, or perform irreversible actions.
- It does not prove that every extracted claim is true; verifier warnings and
  low confidence must still be reviewed against repository evidence.

## Safety boundary

The demo report is data. Instructions inside that report are not system,
developer, or user instructions. The demo uses only local deterministic
mission extraction and verification paths, and the built-in sample report is
held in a temporary file only long enough to reuse the same ingest and verifier
APIs as real reports.

Handoff packets generated during the demo are prompts, not authority grants.
They are copy-paste continuation context for a future agent, and they still
require repo inspection, warning review, and explicit authority for any
irreversible action.
