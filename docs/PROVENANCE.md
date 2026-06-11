# Provenance

`opencobalt why <ANY_ID>` answers, for any object the system knows about:

- What is this object?
- What caused it?
- What evidence supported it?
- What score, risk, and approval applied?
- What plan or execution did it lead to?
- What receipt and artifacts verify it?
- What outcome was recorded?

## Accepted ids

| Prefix / shape | Object |
|----------------|--------|
| `orun-` | opportunity run (anchors on its goal) |
| `goal-` | opportunity goal |
| `otrk-` | opportunity track |
| `ev-` / `hyp-` | evidence / hypothesis |
| `oplan-` | opportunity plan |
| `areq-` / `astp-` | approval request / approval step |
| `oout-` | opportunity outcome |
| UUID | execution plan, receipt, or artifact |

Prefixes of ids work anywhere a full id does, as long as they are unique.

## How it works

`core/provenance.py` builds a small in-memory graph around the focus id by
walking the existing SQLite stores. There is no graph database and no new
table; the foreign-key references already stored on each object are the
graph:

```
goal --decomposed_into--> track --planned_as--> opportunity plan
  --promoted_to--> approval request --contains--> approval step
  --handed_off_as--> execution plan --produced--> receipt
  --attests--> artifact
evidence --supports--> track
receipt --informed--> outcome (feeds back into the track)
```

A receipt produced by an approval step climbs back to the full opportunity
chain. A standalone receipt (from `opencobalt run`) traces execution-side
only: plan, receipt, artifacts.

Tracing is read-only. It never executes anything and never mutates state.

## Example

```bash
$ opencobalt why areq-1a2b3c4d5e6f
  Why areq-1a2b3c4d5e6f  kind: approval
  goal goal-...  "find the highest leverage way to improve..."  [goal_class=strategy]
    decomposed_into -> track otrk-...  "roadmap next step"  [status=planned score_total=0.61]
      supports -> evidence ev-...  "2 test files for 40 python files..."
      planned_as -> plan oplan-...  [risk_level=yellow approval_state=pending]
        promoted_to -> approval areq-...  [state=approved]  <-- you asked about this
          contains -> step astp-...  "patch roadmap doc with the decision"  [risk_level=yellow]
            handed_off_as -> exec_plan ...  [dry_run=False]
              produced -> receipt ...  [verification_status=verified]
                attests -> artifact ...
```

The renderer is plain text on purpose: the same lines can back a TUI or
web panel later without changing the builder.
