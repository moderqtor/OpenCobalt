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
    # Specific credential values that must not appear in the public repo
    re.compile(r'\bcobalt2026\b'),
    re.compile(r'\bcobalt123\b'),
    # Personal email addresses
    re.compile(r'[A-Za-z0-9._%+\-]+@(gmail|yahoo|hotmail)\.com'),
]

_PRIVATE_VAULT_PATTERNS = [
    re.compile(r'~/cobaltos-vault'),
    re.compile(r'/Users/\w+/cobaltos-vault'),
    re.compile(r'COBALT_VAULT\s*[=:]\s*["\']?[^"\'\n]{5,}'),
    re.compile(r'obsidian-vault[/"]'),
    # Absolute user home paths (flags /Users/colin style references)
    re.compile(r'/Users/[A-Za-z][A-Za-z0-9_\-]+(?:/|\s|$)'),
]

# Lines containing these placeholders are safe -- they document what to replace,
# not actual credentials. Skip pattern matches on lines with these strings.
_SAFE_PLACEHOLDER_STRINGS = (
    "[REDACTED",
    "REPLACE_WITH_YOUR_EMAIL",
    "REPLACE_WITH_STRONG_PASSWORD",
    "your_email_here",
    "<placeholder>",
    "your-vault",
    "your_name_here",
)

# Files that contain these strings as pattern definitions, not references
_VAULT_SCAN_SKIP_FILES = {
    "public_safety.py",
    "context.py",
    # Meta-docs that describe the scanning policy (not live configuration)
    "PUBLIC_SAFETY.md",
    "AUDIT_PROMPT.md",
    "REPO_ANALYSIS.md",
}

# Directory name segments exempt from vault-path scanning.
# These paths contain historical audit records and policy documentation
# that legitimately quote the patterns they describe.
_VAULT_SCAN_SKIP_DIRS = {
    "tests",
    "audits",
}

_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "target",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "gen",
    "__pycache__",
    ".pytest_cache",
    ".opencobalt",
    "attachments",
    # Test source files legitimately embed pattern strings as test inputs.
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


def _line_has_safe_placeholder(line: str) -> bool:
    return any(placeholder in line for placeholder in _SAFE_PLACEHOLDER_STRINGS)


def _scan_file_contents(path: Path, rel: str, result: ScanResult) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return

    lines = text.splitlines()

    # Secret pattern scan -- line-by-line so allowlisted lines are skipped
    for pattern in _SECRET_PATTERNS:
        for line in lines:
            if pattern.search(line) and not _line_has_safe_placeholder(line):
                result.secret_hits.append(rel)
                result.issues.append(f"Possible secret pattern in: {rel}")
                return

    # Skip vault path check for files that define patterns (not paths)
    if path.name in _VAULT_SCAN_SKIP_FILES:
        return
    # Skip vault path check for audit/policy subdirectories
    rel_parts = Path(rel).parts
    if any(p in _VAULT_SCAN_SKIP_DIRS for p in rel_parts):
        return

    for pattern in _PRIVATE_VAULT_PATTERNS:
        for line in lines:
            if pattern.search(line) and not _line_has_safe_placeholder(line):
                result.vault_path_hits.append(rel)
                result.issues.append(f"Private vault path reference in: {rel}")
                return
