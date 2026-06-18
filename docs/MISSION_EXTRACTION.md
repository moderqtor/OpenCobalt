# Mission Extraction and Cold Resume v0

Agents come and go. Models change. Sessions die. OpenCobalt remembers.

Mission extraction turns a completed agent/session artifact into durable
mission intelligence attached to a mission in the shared SQLite ledger. The
immediate demo target is cold resume:

```
session output -> mission extraction -> structured mission state -> SQLite
               -> opencobalt continue MISSION_ID -> next session resumes
               -> opencobalt handoff MISSION_ID --to codex-cli -> cold agent resumes
```

## What v0 ships

- A strict structured extraction schema.
- A reusable extraction prompt template in
  `src/opencobalt/core/mission_extractor.py`.
- A deterministic local extractor for offline/test use.
- Heuristic real-session ingest for common Codex, Claude Code, Cursor, and
  OpenCobalt final-report sections.
- Append-only, versioned `mission_extractions` rows linked to `mission_id`.
- `mission.extraction_attached` mission events.
- Deterministic local extraction verification with append-only verifier records.
- `mission.extraction_verified` mission events.
- `missions show`, `missions why`, and generic `why mex-...` / `why mver-...`
  visibility.
- `opencobalt continue MISSION_ID` cold-resume context packages.
- `opencobalt handoff MISSION_ID --to TARGET` prompt packets for `generic`,
  `codex-cli`, `claude-code`, and `cursor`.

## Commands

```bash
opencobalt missions ingest-session MISSION_ID --file path/to/session.txt
opencobalt missions attach-extraction MISSION_ID --json path/to/extraction.json
opencobalt missions verify-extraction MISSION_ID --source-file path/to/report.txt
opencobalt missions show MISSION_ID
opencobalt missions why MISSION_ID
opencobalt continue MISSION_ID
opencobalt handoff MISSION_ID --to generic
opencobalt handoff MISSION_ID --to codex-cli
opencobalt handoff MISSION_ID --to claude-code
opencobalt handoff MISSION_ID --to cursor
```

`ingest-session` uses the deterministic local extractor. It handles plain text,
Markdown, and agent-style bullet reports. It performs no network calls, no
model calls, no subprocess execution, and no raw transcript or raw report
persistence.

`attach-extraction` is the v0 import path for externally generated JSON. Users
can run an LLM outside OpenCobalt if they choose, then attach the validated
result without introducing a hidden network boundary inside OpenCobalt.

`verify-extraction` compares the latest attached extraction, or a selected
`--extraction-id`, against a local source report supplied for that command. It
is deterministic and local. It emits warnings for unsupported claims, completed
status without explicit source evidence, high confidence without direct source
support, missing limitations, missing files, missing commit or test-count
artifacts, suspicious prompt-injection lines, and redacted token-shaped source
content. The verifier stores compact metadata only: support status, confidence
after verification, warning text, redaction metadata, prompt-injection counts,
ids, and timestamps. It does not persist raw source reports.

## Schema

```json
{
  "goal": "",
  "status": "active|blocked|completed|abandoned|unknown",
  "findings": [],
  "decisions": [],
  "assumptions": [],
  "open_questions": [],
  "next_actions": [],
  "files_touched": [],
  "artifacts": [],
  "risks": [],
  "confidence": {
    "goal": "high|medium|low",
    "status": "high|medium|low",
    "findings": "high|medium|low",
    "decisions": "high|medium|low",
    "assumptions": "high|medium|low",
    "open_questions": "high|medium|low",
    "next_actions": "high|medium|low",
    "files_touched": "high|medium|low",
    "artifacts": "high|medium|low",
    "risks": "high|medium|low",
    "overall": "high|medium|low"
  }
}
```

## Extraction Prompt

The reusable prompt template is encoded in the repo for external extractors.
It requires JSON-only output, preserves concrete paths and artifact ids, keeps
uncertain claims in `open_questions`, and forbids marking work completed
without explicit evidence.

OpenCobalt treats transcript text, tool outputs, diffs, receipts, and session
logs as data. Instructions inside those artifacts are not developer or system
instructions.

## Real-Session Heuristics

The local v0 extractor recognizes common final-report sections:

- branch
- base branch/SHA
- test baseline
- final verification
- worktree
- pushed or merged state
- local commit
- summary
- CLI added
- schema added
- persistence behavior
- cold-resume behavior
- manual smoke
- safety findings
- known limitations
- files changed or files touched
- tests added
- next recommendation

These sections are mapped into the settled extraction schema. Summaries become
the extracted goal when no explicit `Goal:` line exists. Final verification,
test baseline, worktree, safety findings, and tests added become findings.
Commit SHAs, PR URLs, mission ids, extraction ids, approval ids, AutoPlan ids,
and test counts are preserved as artifacts when present. Files changed are
stored exactly in `files_touched`. Known limitations and deferred work become
risks or open questions, not findings. Next recommendation becomes a next
action.

Confidence remains conservative. Explicit labeled facts such as a pytest count
or a file path get high confidence. Status inferred from successful final
verification is medium confidence unless the report explicitly says
`Status: completed`. Ambiguous or incomplete evidence stays low confidence.
Token-shaped strings are redacted before structured persistence.

## Cold Resume Package

`opencobalt continue MISSION_ID` prints:

```text
OPENCOBALT MISSION CONTEXT

Mission:
Goal:
Status:
Last known state:

Verification:
Verifier warnings:

Findings:
Decisions:
Assumptions:
Open questions:
Risks:
Files touched:
Artifacts:
Next actions:

Confidence:
Continuation instruction:
You are resuming this mission from OpenCobalt durable mission state. Treat this context as the source of continuity, but verify claims against the repository before making changes.
```

The package is intentionally compact and pasteable. It is not proof. A future
agent should use it as continuity, then verify claims against the repository
before changing files.

If the latest extraction has not been verified, the package says
`Verification: unverified`. If the verifier produced warnings, they are shown
near the top of the package and the confidence block includes the verifier's
overall confidence after verification.

## Handoff Packets

`opencobalt handoff MISSION_ID --to TARGET` renders a copy-paste-ready prompt
packet from the same durable mission state used by `continue`. Supported
targets are:

- `generic`
- `codex-cli`
- `claude-code`
- `cursor`

Every packet includes the sentinel line, mission id, goal, status, latest
extraction id, latest verification id and status when present, verifier
warnings, findings, decisions, assumptions, open questions, risks, files
touched, artifacts, next actions, confidence, required first commands, safety
boundaries, and continuation instructions.

Target-specific sections adapt the same state for the receiving tool:

- `codex-cli` emphasizes repository inspection, `git status` / `git diff`,
  test gates, and no push or merge without explicit authority.
- `claude-code` emphasizes architecture and safety review, avoiding overlapping
  file mutation outside the requested scope, and verifying mission state
  against repository evidence.
- `cursor` emphasizes editor-oriented review and planning, inspecting open
  files and diffs, and no browser, cloud, or remote control unless explicitly
  authorized.
- `generic` stays neutral for any agent.

Handoff packets visibly warn when no extraction exists, the latest extraction
is unverified, verifier warnings exist, or confidence is low. They preserve
structured ids and artifacts such as mission ids, extraction ids, verification
ids, commit SHAs, test counts, file paths, and artifact identifiers that are
already present in durable structured state.

Handoff packets do not execute agents, do not call runtime adapters, do not
start subprocesses, do not call the network, do not create receipts, and do
not grant authority. They are prompts. A receiving agent must treat them as
continuity context, not unquestionable truth, and must verify claims against
the repository before editing.

## Extraction Verifier v0

The v0 verifier reduces false confidence; it does not prove truth. It uses
local, deterministic support checks against the source report available at
verification time. Source reports, transcripts, tool outputs, logs, diffs, and
pasted prompts are untrusted data. The verifier does not execute instructions
inside them, does not run a model, does not call the network, and does not
start subprocesses.

Verifier records are linked to both `mission_id` and `extraction_id`, versioned
per extraction, and append-only. `missions show`, `missions why`, generic
`why mver-...`, and `opencobalt continue` expose verifier status and warnings.

## Safety Boundaries

- v0 is single-pass extraction.
- v0 is heuristic real-session ingest, not a live LLM extractor.
- v0 verification is deterministic/local and is not a live LLM verifier.
- A richer two-pass verifier is future work.
- Live LLM extraction is deferred.
- No hidden model/API/network calls are added.
- No API keys, tokens, credentials, raw environment dumps, cookies, sessions,
  or secrets are stored.
- The raw session transcript or raw agent report is not persisted by
  `ingest-session`.
- The raw source report is not persisted by `verify-extraction`.
- Low confidence stays visible in `show`, `why`, `continue`, and `handoff`.
- Unverified or warning-bearing extractions stay visible in `show`, `why`, and
  `continue` and `handoff`.
- Uncertain claims become open questions instead of facts.
- Handoff packets are prompts, not authority grants.
- Handoff packets do not execute agents or runtimes.
