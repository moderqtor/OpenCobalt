"""Tests for HookManager."""

from __future__ import annotations

import stat
from pathlib import Path

from opencobalt.core.hooks import HOOK_TEMPLATES, HookManager


def test_install_creates_files(tmp_path: Path) -> None:
    hooks_dir = tmp_path / "hooks"
    mgr = HookManager()
    results = mgr.install(hooks_dir)

    assert set(results.keys()) == set(HOOK_TEMPLATES.keys())
    for name in HOOK_TEMPLATES:
        hook_file = hooks_dir / name
        assert hook_file.exists(), f"{name} not created"
        assert results[name] == "installed"
        # Check executable bit
        mode = hook_file.stat().st_mode
        assert mode & stat.S_IXUSR, f"{name} not executable"


def test_install_is_idempotent(tmp_path: Path) -> None:
    hooks_dir = tmp_path / "hooks"
    mgr = HookManager()
    mgr.install(hooks_dir)
    results2 = mgr.install(hooks_dir)
    for name in HOOK_TEMPLATES:
        assert results2[name] == "already installed"


def test_uninstall_only_removes_own_hooks(tmp_path: Path) -> None:
    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()
    mgr = HookManager()

    # Install our hooks
    mgr.install(hooks_dir)

    # Plant a foreign hook
    foreign = hooks_dir / "prepare-commit-msg"
    foreign.write_text("#!/bin/sh\necho 'foreign'\n")

    results = mgr.uninstall(hooks_dir)
    for name in HOOK_TEMPLATES:
        assert results[name] == "removed"
        assert not (hooks_dir / name).exists()

    # Foreign hook untouched
    assert foreign.exists()


def test_status_reports_correctly(tmp_path: Path) -> None:
    hooks_dir = tmp_path / "hooks"
    mgr = HookManager()

    statuses_before = mgr.status(hooks_dir)
    for name in HOOK_TEMPLATES:
        assert statuses_before[name] is False

    mgr.install(hooks_dir)
    statuses_after = mgr.status(hooks_dir)
    for name in HOOK_TEMPLATES:
        assert statuses_after[name] is True


def test_does_not_overwrite_foreign_hooks(tmp_path: Path) -> None:
    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()

    # Plant foreign pre-commit hook (no OpenCobalt marker)
    foreign_content = "#!/bin/sh\n# some other tool\nexit 0\n"
    foreign_hook = hooks_dir / "pre-commit"
    foreign_hook.write_text(foreign_content)

    mgr = HookManager()
    results = mgr.install(hooks_dir)

    assert results["pre-commit"] == "skipped (foreign hook exists)"
    # Content unchanged
    assert foreign_hook.read_text() == foreign_content
