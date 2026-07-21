# OpenCobalt Daily Operator -- User Guide & Workflow Manual

OpenCobalt's **Daily Operator** turns OpenCobalt into a durable, local-first daily operating system for personal execution and efficiency.

---

## 1. Core Product Philosophy

The Daily Operator reduces cognitive overhead by answering 5 fundamental questions:

1. **What matters right now?** → `opencobalt today` / `opencobalt next`
2. **Why does it matter?** → `opencobalt why <id>`
3. **What is the smallest concrete next action?** → `opencobalt next`
4. **What was I doing before I was interrupted?** → `opencobalt focus`
5. **What happened after I acted?** → `opencobalt done` / `opencobalt review`

### Non-Negotiable Guarantees
- **Local-first**: SQLite database (`.opencobalt/ledger.db`). No cloud required.
- **Deterministic core**: Priority scores and state transitions are 100% reproducible.
- **Receipts over claims**: Actions emit verifiable receipts and audit events.
- **Preserve human authority**: Machine recommends; human decides.
- **Zero productivity theater**: No gamification, confetti, or AI fluff.

---

## 2. Command Quick Reference

| Command | Usage | Description |
| :--- | :--- | :--- |
| `opencobalt capture "text"` | Quick capture | Ingest a thought or task into raw inbox |
| `opencobalt inbox` | List inbox | View unclarified raw thoughts |
| `opencobalt clarify <cpt-id>` | Triage capture | Convert capture into action-ready commitment |
| `opencobalt today` | Morning dashboard | View NOW focus, NEXT action, agenda, and blockers |
| `opencobalt next` | Recommendation | Get single top action with priority explanation |
| `opencobalt focus [cmt-id]` | Lock attention | Start or inspect active focus session |
| `opencobalt focus --stop` | End focus | Stop current focus session |
| `opencobalt done <cmt-id>` | Complete task | Record completion, outcome, & optional follow-up |
| `opencobalt defer <cmt-id>` | Postpone task | Move task to future date with rationale |
| `opencobalt waiting <cmt-id>`| Flag dependency | Mark task blocked on person/agent/approval |
| `opencobalt review` | Evening review | Run end-of-day review and save scorecard |
| `opencobalt search "query"`| Search ledger | Search across captures, commitments, & events |
| `opencobalt why <id>` | Provenance trace | Answer why an item exists and trace its lineage |

---

## 3. Daily Operating Workflow

### Morning Sweep (2 Minutes)
1. Open terminal and run:
   ```bash
   opencobalt today
   ```
2. Clear any unclarified thoughts captured yesterday:
   ```bash
   opencobalt inbox
   opencobalt clarify cpt-1234567890ab --impact 4 --due 2026-07-22T17:00:00Z
   ```
3. Request single top recommendation:
   ```bash
   opencobalt next
   ```

### Execution & Focus Block
1. Lock attention on your chosen task:
   ```bash
   opencobalt focus cmt-a1b2c3d4e5f6
   ```
2. If interrupted by an urgent call or message:
   ```bash
   opencobalt capture "Urgent call with advisor"
   opencobalt focus cmt-urgent
   ```
3. Complete task and record outcome:
   ```bash
   opencobalt done cmt-a1b2c3d4e5f6 --summary "Drafted advocacy paper outline" --follow-up "Email draft to advisor"
   ```

### Evening Review (2 Minutes)
1. Run daily review protocol:
   ```bash
   opencobalt review
   ```
2. Trace any decision or commitment lineage:
   ```bash
   opencobalt why cmt-a1b2c3d4e5f6
   ```

---

## 4. Machine-Readable (--json) Usage

All commands support `--json` (or `-j`) for scripting, subagents, and IDE extensions:

```bash
opencobalt today --json
opencobalt next --json
opencobalt done cmt-a1b2c3d4e5f6 --summary "Finished" --json
```

---

## 5. Storage, Backup & Privacy

- **Data Location**: Single local SQLite database at `.opencobalt/ledger.db`.
- **Backup**: Simply copy `.opencobalt/ledger.db` to your backup location.
- **Privacy**: No telemetry or capture content leaves your local machine.

---
