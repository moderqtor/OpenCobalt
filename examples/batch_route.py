"""Example: batch routing -- route a list of tasks and summarize results."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from collections import Counter
from opencobalt.core.router import route_task

tasks = [
    "design the memory system schema",
    "summarize yesterday's session log",
    "extract tags from meeting notes",
    "write integration tests for the ledger",
    "fix the authentication bug on line 42",
    "review the public safety scanner for edge cases",
    "compress and archive old log files",
    "design the agent communication protocol",
    "paraphrase this paragraph for clarity",
    "implement the event spine API",
]

decisions = [route_task(t) for t in tasks]

tier_counts: Counter = Counter(d.tier for d in decisions)
tool_counts: Counter = Counter(d.recommended_tool for d in decisions)

print("Batch Routing Results")
print("=" * 60)
print(f"{'Task':<48} {'Tool':<14} {'Tier'}")
print("-" * 80)
for d in decisions:
    print(f"{d.task[:47]:<48} {d.recommended_tool:<14} {d.tier}")

print()
print("Summary")
print("-" * 40)
for tier, count in sorted(tier_counts.items()):
    print(f"  {tier:<12} {count} task(s)")
print()
for tool, count in tool_counts.most_common():
    print(f"  {tool:<16} {count} task(s)")
