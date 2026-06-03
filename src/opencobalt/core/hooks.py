"""Git hook manager for automatic OpenCobalt logging."""

from __future__ import annotations

import stat
from pathlib import Path

_MARKER = "# OpenCobalt:"

HOOK_TEMPLATES: dict[str, str] = {
    "pre-commit": """\
#!/bin/sh
# OpenCobalt: security scan before commit
opencobalt public-check || exit 1
""",
    "post-commit": """\
#!/bin/sh
# OpenCobalt: log commit to session ledger
MSG=$(git log -1 --pretty=%B)
opencobalt note "committed: $MSG" --tags git,commit 2>/dev/null || true
""",
    "pre-push": """\
#!/bin/sh
# OpenCobalt: verify before push
opencobalt verify 2>/dev/null || true
""",
}


class HookManager:
    """Install, uninstall, and report status of OpenCobalt git hooks."""

    def install(self, hooks_dir: Path) -> dict[str, str]:
        hooks_dir.mkdir(parents=True, exist_ok=True)
        results: dict[str, str] = {}
        for name, template in HOOK_TEMPLATES.items():
            hook_path = hooks_dir / name
            if hook_path.exists():
                existing = hook_path.read_text(encoding="utf-8")
                if _MARKER in existing:
                    results[name] = "already installed"
                    continue
                # Foreign hook -- skip without overwriting
                results[name] = "skipped (foreign hook exists)"
                continue
            hook_path.write_text(template, encoding="utf-8")
            _make_executable(hook_path)
            results[name] = "installed"
        return results

    def uninstall(self, hooks_dir: Path) -> dict[str, str]:
        results: dict[str, str] = {}
        for name in HOOK_TEMPLATES:
            hook_path = hooks_dir / name
            if not hook_path.exists():
                results[name] = "not found"
                continue
            content = hook_path.read_text(encoding="utf-8")
            if _MARKER not in content:
                results[name] = "skipped (not an OpenCobalt hook)"
                continue
            hook_path.unlink()
            results[name] = "removed"
        return results

    def status(self, hooks_dir: Path) -> dict[str, bool]:
        result: dict[str, bool] = {}
        for name in HOOK_TEMPLATES:
            hook_path = hooks_dir / name
            if not hook_path.exists():
                result[name] = False
                continue
            content = hook_path.read_text(encoding="utf-8")
            result[name] = _MARKER in content
        return result


def _make_executable(path: Path) -> None:
    current = path.stat().st_mode
    path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
