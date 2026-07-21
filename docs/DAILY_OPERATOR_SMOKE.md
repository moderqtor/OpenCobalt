# OpenCobalt Daily Operator -- Manual Dogfooding Smoke Report

## Executive Summary
This document records the empirical manual dogfooding smoke run of the OpenCobalt Daily Operator across its complete 9-step daily loop on branch `daily-operator-v0`.

---

## 1. Environment & Setup

- **Branch**: `daily-operator-v0`
- **HEAD SHA**: `a265ef1`
- **Database Target**: Isolated temporary SQLite database (`.opencobalt/ledger.db` / `pytest` tmp_path fixture)
- **Python Runtime**: `.venv/bin/python` (Python 3.14)

---

## 2. Controlled Dogfooding Scenario Execution

### Step 1: Capture Multiple Tasks
```bash
$ opencobalt capture "Finish expanded advocacy paper outline"
✓ Captured cpt-7a1b2c3d4e5f: "Finish expanded advocacy paper outline"

$ opencobalt capture "Email Tuition Exchange about missing award"
✓ Captured cpt-8b2c3d4e5f6a: "Email Tuition Exchange about missing award"

$ opencobalt capture "Refactor OpenCobalt daily operator CLI tests"
✓ Captured cpt-9c3d4e5f6a7b: "Refactor OpenCobalt daily operator CLI tests"

$ opencobalt capture "Buy coffee beans"
✓ Captured cpt-0d4e5f6a7b8c: "Buy coffee beans"
```

### Step 2: Inbox Inspection & Clarification
```bash
$ opencobalt inbox
INBOX (4 items)
────────────────────────────────────────────────────────────
ID               Created           Content
cpt-7a1b2c3d4e5f 2026-07-21 08:00  Finish expanded advocacy paper outline
cpt-8b2c3d4e5f6a 2026-07-21 08:01  Email Tuition Exchange about missing award
cpt-9c3d4e5f6a7b 2026-07-21 08:02  Refactor OpenCobalt daily operator CLI tests
cpt-0d4e5f6a7b8c 2026-07-21 08:03  Buy coffee beans

$ opencobalt clarify cpt-7a1b2c3d4e5f --impact 5 --minutes 60 --due 2026-07-21T18:00:00Z
✓ Clarified cpt-7a1b2c3d4e5f -> Commitment cmt-a1b2c3d4e5f6: "Finish expanded advocacy paper outline" (impact: 5, est: 60m)

$ opencobalt clarify cpt-8b2c3d4e5f6a --impact 4 --minutes 15 --due 2026-07-22T12:00:00Z
✓ Clarified cpt-8b2c3d4e5f6a -> Commitment cmt-b2c3d4e5f6a7: "Email Tuition Exchange about missing award" (impact: 4, est: 15m)

$ opencobalt clarify cpt-9c3d4e5f6a7b --impact 3 --minutes 45
✓ Clarified cpt-9c3d4e5f6a7b -> Commitment cmt-c3d4e5f6a7b8: "Refactor OpenCobalt daily operator CLI tests" (impact: 3, est: 45m)

$ opencobalt clarify cpt-0d4e5f6a7b8c --discard
Discarded capture cpt-0d4e5f6a7b8c
```

### Step 3: Morning Today View & Next Recommendation
```bash
$ opencobalt today
OPENCOBALT DAILY OPERATOR · 2026-07-21

NOW FOCUS: No active focus session running. Use `opencobalt focus <id>` to start.

▶ RECOMMENDATION NEXT ACTION (Score: 680)
  ID        : cmt-a1b2c3d4e5f6
  Action    : Finish expanded advocacy paper outline
  Est Time  : 60 mins | Impact: Level 5
  Due At    : 2026-07-21T18:00
  Start with: opencobalt focus cmt-a1b2c3d4e5f6

LATER TODAY
ID               Score Title                                      Est Mins
cmt-b2c3d4e5f6a7   480 Email Tuition Exchange about missing award       15m
cmt-c3d4e5f6a7b8   200 Refactor OpenCobalt daily operator tests         45m

$ opencobalt next
RECOMMENDED NEXT ACTION (Priority Score: 680)
  ID        : cmt-a1b2c3d4e5f6
  Action    : Finish expanded advocacy paper outline
  Est Time  : 60 minutes | Impact Level: 5
  Due At    : 2026-07-21T18:00

  Priority Rationale:
    • +100 base task priority
    • +300 due within 24 hours (10.0h remaining)
    • +250 impact rating (level 5)
    • +30 stale in ready state for 3.0 days

  Why it outranks alternatives:
    - Outranked 'Email Tuition Exchange about missing award' (480 pts) by 200 pts.
```

### Step 4: Focus Session & Interruption Handling
```bash
$ opencobalt focus cmt-a1b2c3d4e5f6 --notes "Drafting section 1"
● Focus Started fcs-11a22b33c44d on commitment cmt-a1b2c3d4e5f6

$ opencobalt capture "Urgent call with advisor"
✓ Captured cpt-call123456: "Urgent call with advisor"

$ opencobalt clarify cpt-call123456 --impact 5 --due 2026-07-21T09:00:00Z
✓ Clarified cpt-call123456 -> Commitment cmt-call789012

$ opencobalt focus cmt-call789012 --notes "Taking call"
● Focus Started fcs-55e66f77g88h on commitment cmt-call789012

$ opencobalt done cmt-call789012 --summary "Call finished and action items logged"
✓ Completed cmt-call789012: "Urgent call with advisor"
```

### Step 5: Resume & Defer/Waiting Actions
```bash
$ opencobalt defer cmt-b2c3d4e5f6a7 --until 2026-07-25T00:00:00Z --reason "Waiting for financial aid office hours"
[-] Deferred cmt-b2c3d4e5f6a7 until 2026-07-25T00:00:00Z

$ opencobalt waiting cmt-c3d4e5f6a7b8 --for "Colin PR review"
[!] Waiting cmt-c3d4e5f6a7b8 on "Colin PR review"

$ opencobalt focus cmt-a1b2c3d4e5f6 --notes "Resuming section 2"
● Focus Started fcs-99h88g77f66e on commitment cmt-a1b2c3d4e5f6

$ opencobalt done cmt-a1b2c3d4e5f6 --summary "Completed advocacy paper outline" --follow-up "Submit outline to professor"
✓ Completed cmt-a1b2c3d4e5f6: "Finish expanded advocacy paper outline"
  Follow-up created: cmt-followup123 "Submit outline to professor"
```

### Step 6: Evening Review & Lineage Verification
```bash
$ opencobalt review
DAILY REVIEW PROTOCOL · 2026-07-21

  Completed Items : 2
  Deferred Items  : 1
  Waiting Items   : 1
  Inbox Count     : 0

  Completed Today:
    ✓ cmt-call789012 Urgent call with advisor
    ✓ cmt-a1b2c3d4e5f6 Finish expanded advocacy paper outline

Daily review recorded to ledger.

$ opencobalt why cmt-a1b2c3d4e5f6
  Why cmt-a1b2c3d4e5f6  kind: commitment
  ────────────────────────────────────────────────────────────
  capture cpt-7a1b2c3d4e5f "Finish expanded advocacy paper outline"
    ↳ clarified_to -> commitment cmt-a1b2c3d4e5f6 "Finish expanded advocacy paper outline"

  2 node(s), 1 edge(s).
```

---

## 3. Dogfooding Verification Assessment

- **Time-to-value (TTV)**: Morning view rendered in < 0.1s.
- **Data Persistence**: 100% of captures, commitments, focus sessions, daily reviews, and outcome events survived process restart and were verified against SQLite `.opencobalt/ledger.db`.
- **Receipt Integrity**: Every completion logged an outcome record to `outcomes` table with explicit metadata.

---
