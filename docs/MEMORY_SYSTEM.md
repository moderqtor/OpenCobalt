# Memory System

## Design

SQLite is the source of truth. All memory is stored in `.opencobalt/ledger.db`.

Markdown exports are generated mirrors. They are not the source of truth. Never edit them manually -- regenerate from the ledger.

The private Obsidian vault is not a dependency. If you want to export memory records to Obsidian, configure the export path in `.env`. It is disabled by default.

## Schema

```sql
memory_records (
    id        TEXT PRIMARY KEY,   -- UUID
    timestamp TEXT NOT NULL,      -- UTC ISO 8601
    project   TEXT NOT NULL,      -- project identifier
    namespace TEXT NOT NULL,      -- e.g. "ideas", "notes", "decisions"
    content   TEXT NOT NULL,      -- the memory content
    source    TEXT NOT NULL,      -- e.g. "cli", "agent", "import"
    metadata  TEXT NOT NULL       -- JSON blob for extensible fields
)
```

## Usage

```bash
# Write a memory record from the CLI
opencobalt log --summary "decided to use SQLite for ledger"

# View memory status
opencobalt memory status

# Export to markdown
opencobalt memory export --project opencobalt
```

## Programmatic Use

```python
from opencobalt.core.ledger import Ledger
from opencobalt.core.memory import MemoryStore

ledger = Ledger()
store = MemoryStore(ledger)

# Write
store.write("myproject", "decisions", "Use Typer for CLI", source="session")

# Read
records = store.read("myproject", namespace="decisions")

# Export markdown mirror
from pathlib import Path
store.export_markdown("myproject", Path("exports/myproject-memory.md"))
```

## Export Rules

- Exports go to `.opencobalt/exports/<project>-memory.md` by default
- Exports are generated from SQLite on demand
- Exports are gitignored (they are runtime artifacts, not repo content)
- Sample exports may be committed explicitly if needed for documentation
- The Obsidian vault is never written unless the export path is configured to point there

## Namespaces

Use namespaces to organize memory by type. Common patterns:

| Namespace | Purpose |
|-----------|---------|
| decisions | Architecture and design decisions |
| ideas | Raw ideas to develop later |
| notes | Session notes and observations |
| issues | Known bugs or problems |
| refs | External references and links |

Namespaces are free-form strings -- define your own schema per project.
