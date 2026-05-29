"""Example: building a context pack programmatically."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from opencobalt.core.context import build_context_pack

output_path = Path(".opencobalt/context/example-pack.md")
pack = build_context_pack(project="opencobalt", output=output_path)

print("Context pack built:")
print(f"  files     : {len(pack.sources)}")
print(f"  tokens    : ~{pack.token_estimate:,}")
print(f"  output    : {output_path}")
print()
print("Sources included:")
for src in pack.sources[:10]:
    print(f"  {src}")
if len(pack.sources) > 10:
    print(f"  ... and {len(pack.sources) - 10} more")
