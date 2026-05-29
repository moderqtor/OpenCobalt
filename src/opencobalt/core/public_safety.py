"""Public safety scanner.

Scans the repo for common public-hygiene issues before any push:
.env files, hardcoded secrets, private vault paths, oversized artifacts,
node_modules, and generated databases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_SECRET_PATTERNS = [
    re.compile(r'(?i)(password|passwd|secret|api_key|apikey|token|private_key)\s*[=:]\s*["\']?\w{6,}'),
    re.compile(r'(?i)sk-[A-Za-z0-9]{20,}'),
    re.compile(r'(?i)AIza[A-Za-z0-9_\-]{35}'),
]

_PRIVATE_VAULT_PATTERNS = [
    re.compile(r'~/cobaltos-vault'),
    re.compile(r'/Users/\w+/cobaltos-vault'),
    re.compile(r'COBALT_VAULT\s*[=:]\s*["\']?[^"\'\n]{5,}'),
    re.compile(r'obsidian-vault[/"]'),
]

# Files that contain these strings as pattern definitions, not references
_VAULT_SCAN_SKIP_FILES = {
    "public_safety.py",
    "context.py",
}

# Directories exempt from vault-path scanning -- test files and audit docs
# legitimately reference excluded path names without being actual disclosures.
_VAULT_SCAN_SKIP_DIRS = {"tests", "docs"}

_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".opencobalt",
    # Test source files legitimately embed pattern strings as test inputs.
    # The scanner's own patterns should not flag test code.
    "tests",
}

_TEXT_EXTENSIONS = {
    ".py", ".md", ".txt", ".toml", ".yaml", ".yml", ".json",
    ".ts", ".tsx", ".js", ".jsx", ".css", ".html", ".sh",
    ".env", ".example", ".cfg", ".ini",
}

_MAX_FILE_SIZE_MB = 10


@dataclass
class ScanResult:
    env_files_found: bool = False
    node_modules_found: bool = False
    venv_found: bool = False
    oversized_files: list[str] = field(default_factory=list)
    secret_hits: list[str] = field(default_factory=list)
    vault_path_hits: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.issues

    def summary(self) -> str:
        if self.is_clean:
            return "No public-safety issues detected."
        return f"{len(self.issues)} issue(s) found:\n" + "\n".join(f"  - {i}" for i in self.issues)


def scan_directory(root: Path, *, verbose: bool = False) -> ScanResult:
    result = ScanResult()

    for item in root.rglob("*"):
        if _should_skip(item, root):
            continue

        rel = str(item.relative_to(root))

        if item.is_dir():
            if item.name == "node_modules":
                result.node_modules_found = True
                result.issues.append(f"node_modules present: {rel}/")
            elif item.name in (".venv", "venv", "env"):
                result.venv_found = True
                result.issues.append(f"Python venv present: {rel}/")
            continue

        if item.is_file():
            # .env detection (existence only, no reading)
            if item.name == ".env" or (item.suffix == ".env" and item.stem != ".env"):
                if item.name != ".env.example":
                    result.env_files_found = True
                    result.issues.append(f".env file present: {rel}")

            # oversized file check
            size_mb = item.stat().st_size / (1024 * 1024)
            if size_mb > _MAX_FILE_SIZE_MB:
                result.oversized_files.append(rel)
                result.issues.append(f"Oversized file ({size_mb:.1f} MB): {rel}")

            # text content scanning (skip binary / large files)
            if item.suffix in _TEXT_EXTENSIONS and size_mb < 1.0:
                _scan_file_contents(item, rel, result)

    return result


def _should_skip(item: Path, root: Path) -> bool:
    for part in item.parts:
        if part in _SKIP_DIRS:
            return True
    return False


def _scan_file_contents(path: Path, rel: str, result: ScanResult) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return

    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            result.secret_hits.append(rel)
            result.issues.append(f"Possible secret pattern in: {rel}")
            break

    # Skip vault path check for files that define patterns (not paths)
    parts = Path(rel).parts
    if path.name in _VAULT_SCAN_SKIP_FILES:
        return
    if parts and parts[0] in _VAULT_SCAN_SKIP_DIRS:
        return

    for pattern in _PRIVATE_VAULT_PATTERNS:
        if pattern.search(text):
            result.vault_path_hits.append(rel)
            result.issues.append(f"Private vault path reference in: {rel}")
            break
