# Mission Extraction and Cold Resume v0

Agents come and go. Models change. Sessions die. OpenCobalt remembers.

Mission extraction turns a completed agent/session artifact into durable
mission intelligence attached to a mission in the shared SQLite ledger. The
immediate demo target is cold resume:

```
session output -> mission extraction -> structured mission state -> SQLite
               -> opencobalt continue MISSION_ID -> next session resumes
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
- `missions show`, `missions why`, and generic `why mex-...` visibility.
- `opencobalt continue MISSION_ID` cold-resume context packages.

## Commands

```bash
opencobalt missions ingest-session MISSION_ID --file path/to/session.txt
opencobalt missions attach-extraction MISSION_ID --json path/to/extraction.json
opencobalt missions show MISSION_ID
opencobalt missions why MISSION_ID
opencobalt continue MISSION_ID
```

`ingest-session` uses the deterministic local extractor. It handles plain text,
Markdown, and agent-style bullet reports. It performs no network calls, no
model calls, no subprocess execution, and no raw transcript or raw report
persistence.

`attach-extraction` is the v0 import path for externally generated JSON. Users
can run an LLM outside OpenCobalt if they choose, then attach the validated
result without introducing a hidden network boundary inside OpenCobalt.

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

## Safety Boundaries

- v0 is single-pass extraction.
- v0 is heuristic real-session ingest, not a live LLM extractor.
- The two-pass verifier is future work.
- Live LLM extraction is deferred.
- No hidden model/API/network calls are added.
- No API keys, tokens, credentials, raw environment dumps, cookies, sessions,
  or secrets are stored.
- The raw session transcript or raw agent report is not persisted by
  `ingest-session`.
- Low confidence stays visible in `show`, `why`, and `continue`.
- Uncertain claims become open questions instead of facts.
