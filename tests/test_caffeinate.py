"""Tests for the optional caffeinate (keep-awake) wrapper.

All platform and subprocess behavior is mocked; no caffeinate process is
ever actually started.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from opencobalt.execution.caffeinate import caffeinate_available, keep_awake

_MOD = "opencobalt.execution.caffeinate"


def _macos_with_binary():
    return (
        patch(f"{_MOD}.platform.system", return_value="Darwin"),
        patch(f"{_MOD}.shutil.which", return_value="/usr/bin/caffeinate"),
    )


class TestAvailability:
    def test_available_on_macos_with_binary(self):
        sys_patch, which_patch = _macos_with_binary()
        with sys_patch, which_patch:
            assert caffeinate_available() is True

    def test_unavailable_on_linux(self):
        with patch(f"{_MOD}.platform.system", return_value="Linux"):
            assert caffeinate_available() is False

    def test_unavailable_without_binary(self):
        with (
            patch(f"{_MOD}.platform.system", return_value="Darwin"),
            patch(f"{_MOD}.shutil.which", return_value=None),
        ):
            assert caffeinate_available() is False


class TestKeepAwake:
    def test_disabled_is_noop(self):
        with patch(f"{_MOD}.subprocess.Popen") as popen:
            with keep_awake(False) as active:
                assert active is False
            popen.assert_not_called()

    def test_noop_on_unsupported_platform(self):
        with (
            patch(f"{_MOD}.platform.system", return_value="Linux"),
            patch(f"{_MOD}.subprocess.Popen") as popen,
        ):
            with keep_awake(True) as active:
                assert active is False
            popen.assert_not_called()

    def test_starts_scoped_process_on_macos(self):
        sys_patch, which_patch = _macos_with_binary()
        proc = MagicMock()
        with (
            sys_patch,
            which_patch,
            patch(f"{_MOD}.os.getpid", return_value=4242),
            patch(f"{_MOD}.subprocess.Popen", return_value=proc) as popen,
        ):
            with keep_awake(True) as active:
                assert active is True
            argv = popen.call_args.args[0]
            assert argv == ["caffeinate", "-dims", "-w", "4242"]
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once()

    def test_terminates_on_exception(self):
        sys_patch, which_patch = _macos_with_binary()
        proc = MagicMock()
        with sys_patch, which_patch, patch(f"{_MOD}.subprocess.Popen", return_value=proc):
            try:
                with keep_awake(True):
                    raise RuntimeError("simulated failure mid-run")
            except RuntimeError:
                pass
        proc.terminate.assert_called_once()

    def test_kills_if_terminate_hangs(self):
        sys_patch, which_patch = _macos_with_binary()
        proc = MagicMock()
        proc.wait.side_effect = subprocess.TimeoutExpired(cmd="caffeinate", timeout=5)
        with sys_patch, which_patch, patch(f"{_MOD}.subprocess.Popen", return_value=proc):
            with keep_awake(True):
                pass
        proc.kill.assert_called_once()

    def test_popen_failure_degrades_to_noop(self):
        sys_patch, which_patch = _macos_with_binary()
        with (
            sys_patch,
            which_patch,
            patch(f"{_MOD}.subprocess.Popen", side_effect=OSError("no fork")),
        ):
            with keep_awake(True) as active:
                assert active is False
