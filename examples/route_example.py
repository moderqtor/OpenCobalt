"""Example: programmatic task routing with OpenCobalt."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from opencobalt.core.router import route_task

tasks = [
    "design the authentication module architecture",
    "summarize this log file",
    "write unit tests for the router",
    "fix the null pointer exception in events.py",
    "tag these notes for the knowledge base",
]

print("OpenCobalt Router -- Task Routing Examples")
print("-" * 60)

for task in tasks:
    decision = route_task(task)
    print(f"\nTask:  {task}")
    print(f"Route: {decision.recommended_tool} ({decision.tier} tier, score {decision.score})")
    print(f"       {decision.reasoning}")
