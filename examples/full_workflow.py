"""Example: full OpenCobalt workflow -- session, routing, agents, stats.

Demonstrates the complete pipeline:
  1. Start a named session
  2. Route several tasks (decisions are tagged with session name)
  3. Run the code-reviewer agent on a real file
  4. Show session decisions
  5. Show ledger stats
  6. End the session

Run from the repo root:
  python3 examples/full_workflow.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from opencobalt.agents.registry import get_agent
from opencobalt.core.ledger import Ledger
from opencobalt.core.router import route_task
from opencobalt.core.session import SessionManager

_DB_PATH = Path(".opencobalt") / "ledger.db"
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def separator(label: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {label}")
    print(f"{'─' * 60}")


def main() -> None:
    ledger = Ledger(_DB_PATH)
    session = SessionManager(_DB_PATH)

    # 1. Start session
    separator("Session: start")
    session.start("workflow-demo")
    print("  Session started: workflow-demo")

    # 2. Route a set of tasks
    separator("Router: task routing")
    tasks = [
        "design the authentication module architecture",
        "summarize the session log file",
        "write tests for the ledger module",
        "extract tags from these meeting notes",
        "review the public safety scanner for edge cases",
    ]

    for task in tasks:
        decision = route_task(task, record=False)
        # Tag with session name before recording
        decision.metadata["_session"] = "workflow-demo"
        ledger.insert_route_decision(decision)
        print(f"  [{decision.tier:>9}]  {decision.recommended_tool:<14}  {task[:50]}")

    # 3. Code reviewer agent on a real file
    separator("Agent: code-reviewer")
    reviewer = get_agent("code-reviewer")
    if reviewer:
        result = reviewer.run("src/opencobalt/core/router.py")
        # Print just the metrics section
        lines = result.split("\n")
        for line in lines[:12]:
            print(f"  {line}")
        print("  ...")

    # 4. Show session decisions
    separator("Session: decisions")
    all_decisions = ledger.list_route_decisions(limit=100)
    session_decisions = [d for d in all_decisions if d.metadata.get("_session") == "workflow-demo"]
    print(f"  {len(session_decisions)} decision(s) in session workflow-demo")
    for d in session_decisions:
        ts = d.timestamp.strftime("%H:%M") if hasattr(d.timestamp, "strftime") else "??:??"
        print(f"  {ts}  {d.recommended_tool:<14} ({d.tier})  {d.task[:45]}")

    # 5. Ledger stats
    separator("Stats: ledger summary")
    from collections import Counter
    tier_counts: Counter = Counter(d.tier for d in all_decisions)
    tool_counts: Counter = Counter(d.recommended_tool for d in all_decisions)
    print(f"  Total route decisions: {len(all_decisions)}")
    for tier, count in sorted(tier_counts.items()):
        print(f"  {tier:<12} {count}")
    print()
    for tool, count in tool_counts.most_common(3):
        print(f"  {tool:<16} {count}")

    # 6. End session
    separator("Session: end")
    name = session.end()
    print(f"  Session ended: {name}")
    print()


if __name__ == "__main__":
    main()
