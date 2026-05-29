# Public Safety Policy

## Purpose

This document defines what is excluded from the public OpenCobalt repo, how that exclusion is enforced, and why.

## What Is Excluded

### Credentials and secrets
- `.env` files of any kind (except `.env.example`)
- API keys
- Database passwords or connection strings with credentials
- Service account files
- Private keys (`.pem`, `.key`, `.p12`)

### Private data
- Raw session logs from development
- Personal Obsidian vault content
- Obsidian vault ChromaDB indexes
- Private memory store files (JSONL)
- Generated SQLite databases (`.opencobalt/ledger.db` is gitignored)
- Screenshots that include private information

### Generated artifacts
- `node_modules/`
- `.venv/` and `venv/`
- `__pycache__/`
- `.pytest_cache/`
- ChromaDB data directories
- Qdrant storage

### Third-party code
- No vendored copies of third-party repos
- No symlinks to third-party repos
- Dependencies via pip only (declared in `pyproject.toml`)

## Enforcement

The `public-check` command runs a scanner before any push:

```bash
opencobalt public-check
```

The scanner detects:
- `.env` files (by filename, content not read)
- Hardcoded secret patterns (regex on Python, YAML, TOML, shell files)
- Private vault path references (`~/cobaltos-vault`, absolute user paths)
- Oversized files (over 10 MB)
- `node_modules/` or `.venv/` directories

The `.gitignore` is the first line of defense. The scanner is the second.

## Source Repo Treatment

The private `~/dev/AI` repo (Cobalt Forge) is treated as untrusted source material:
- Never copied wholesale
- Each file audited before any content is extracted
- Adapted and rewritten, not dumped
- Logs, memory stores, vault indexes, and `.env` files are permanently excluded
- See `docs/EXCLUDED_SOURCES.md` for the complete exclusion list

## Running a Scan Manually

```python
from pathlib import Path
from opencobalt.core.public_safety import scan_directory

result = scan_directory(Path("."))
print(result.summary())
```
