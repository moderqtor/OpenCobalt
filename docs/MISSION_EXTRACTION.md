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

`ingest-session` uses the deterministic local extractor. It performs no network
calls, no model calls, no subprocess execution, and no raw transcript
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
- The two-pass verifier is future work.
- Live LLM extraction is deferred.
- No hidden model/API/network calls are added.
- No API keys, tokens, credentials, raw environment dumps, cookies, sessions,
  or secrets are stored.
- The raw session transcript is not persisted by `ingest-session`.
- Low confidence stays visible in `show`, `why`, and `continue`.
- Uncertain claims become open questions instead of facts.
