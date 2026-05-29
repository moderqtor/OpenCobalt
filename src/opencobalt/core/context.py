"""Context pack compiler.

Builds compact context packs from README, docs, and selected project files.
Writes output to .opencobalt/context/latest.md.
Never includes gitignored, private, or binary files.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

from .models import ContextPack

_DEFAULT_OUTPUT = Path(".opencobalt") / "context" / "latest.md"

_INCLUDE_EXTENSIONS = {".py", ".md", ".toml", ".txt", ".yaml", ".yml"}
_EXCLUDE_PATTERNS = [
    "*.db", "*.jsonl", "*.sqlite", "*.sqlite3",
    ".env", ".env.*", "*.pem", "*.key",
    "__pycache__/*", "*.pyc", ".pytest_cache/*",
    "node_modules/*", ".venv/*", "venv/*",
    ".opencobalt/*", "vault_index/*", "memory_store/*", "logs/*",
    "assets/screenshots/*", "assets/readme/*",
]
_MAX_FILE_CHARS = 8_000
_MAX_TOTAL_CHARS = 60_000


def build_context_pack(
    root: Path | None = None,
    output: Path | None = None,
    project: str = "opencobalt",
) -> ContextPack:
    """Compile a context pack and write it to disk.

    Prioritizes README, docs/, then src/ files. Caps total size.
    """
    root = (root or Path(".")).resolve()
    output = output or _DEFAULT_OUTPUT

    sources: list[str] = []
    sections: list[str] = []
    total_chars = 0

    candidates = _prioritized_candidates(root)
    for path in candidates:
        if total_chars >= _MAX_TOTAL_CHARS:
            break
        rel = str(path.relative_to(root))
        if _is_excluded(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if len(text) > _MAX_FILE_CHARS:
            text = text[:_MAX_FILE_CHARS] + "\n\n[... truncated ...]\n"
        section = f"## {rel}\n\n```\n{text}\n```\n"
        sections.append(section)
        sources.append(rel)
        total_chars += len(text)

    content = f"# OpenCobalt Context Pack\n\nProject: {project}\nFiles: {len(sources)}\n\n---\n\n" + "\n".join(sections)
    token_estimate = total_chars // 4  # rough approximation

    output.parent.mkdir(parents=True, exist_ok=True)
    # Save previous version before overwriting so diff is available
    if output.exists():
        prev = output.parent / "previous.md"
        prev.write_text(output.read_text(encoding="utf-8"), encoding="utf-8")
    output.write_text(content, encoding="utf-8")

    return ContextPack(
        project=project,
        sources=sources,
        content=content,
        token_estimate=token_estimate,
    )


def _prioritized_candidates(root: Path) -> list[Path]:
    priority: list[Path] = []
    rest: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in _INCLUDE_EXTENSIONS:
            continue
        rel = str(path.relative_to(root))
        if _is_excluded(rel):
            continue
        parts = path.relative_to(root).parts
        if parts[0] in ("docs", "README.md") or path.name == "README.md":
            priority.append(path)
        else:
            rest.append(path)
    return priority + rest


def _is_excluded(rel: str) -> bool:
    for pattern in _EXCLUDE_PATTERNS:
        if fnmatch.fnmatch(rel, pattern):
            return True
        if fnmatch.fnmatch(Path(rel).name, pattern):
            return True
    return False
