"""Release-facing tests for the single-command local UI launcher."""

from __future__ import annotations

import socket
import subprocess
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from opencobalt.cli import (
    _listener_command_line,
    _reclaim_stale_opencobalt_listener,
    _require_available_ui_port,
    app,
)


def _unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_ui_port_probe_retries_a_released_port_without_hiding_a_listener(
    monkeypatch,
) -> None:
    bind_attempts = iter([False, True])
    listener_checks = []
    sleeps = []
    monkeypatch.setattr(
        "opencobalt.cli._can_bind_ui_port",
        lambda _port: next(bind_attempts),
    )
    monkeypatch.setattr(
        "opencobalt.cli._ui_port_has_listener",
        lambda port: listener_checks.append(port) or False,
    )
    monkeypatch.setattr("time.sleep", lambda seconds: sleeps.append(seconds))

    _require_available_ui_port("UI", 5198)

    assert listener_checks == [5198]
    assert sleeps == [0.1]


def test_stale_listener_reclaim_requires_opencobalt_ownership(monkeypatch) -> None:
    monkeypatch.setattr("opencobalt.cli._opencobalt_owned_listener", lambda port, label: None)
    assert _reclaim_stale_opencobalt_listener(8000, "API") is False


def test_listener_command_line_uses_portable_ps_when_proc_is_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda _path: (_ for _ in ()).throw(FileNotFoundError("no procfs")),
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="uvicorn opencobalt.api_server:app --port 8000\n",
        ),
    )

    assert _listener_command_line(4242) == (
        "uvicorn opencobalt.api_server:app --port 8000"
    )


def test_stale_opencobalt_listener_is_reclaimed(monkeypatch) -> None:
    killed = []
    monkeypatch.setattr(
        "opencobalt.cli._opencobalt_owned_listener",
        lambda port, label: (4242, "uvicorn opencobalt.api_server:app --port 8000"),
    )
    monkeypatch.setattr("os.kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(
        "opencobalt.cli._listener_has_live_ui_launcher_ancestor", lambda pid: False
    )
    monkeypatch.setattr(
        "opencobalt.cli._opencobalt_listener_is_healthy", lambda port, label: False
    )
    monkeypatch.setattr("opencobalt.cli._ui_port_has_listener", lambda port: False)
    monkeypatch.setattr("opencobalt.cli._can_bind_ui_port", lambda port: True)
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    assert _reclaim_stale_opencobalt_listener(8000, "API") is True
    assert killed[0][0] == 4242


def test_stale_listener_is_not_killed_if_ownership_changes(monkeypatch) -> None:
    ownership_checks = iter(
        [
            (4242, "uvicorn opencobalt.api_server:app --port 8000"),
            (4343, "python unrelated_server.py"),
        ]
    )
    monkeypatch.setattr(
        "opencobalt.cli._opencobalt_owned_listener",
        lambda port, label: next(ownership_checks),
    )
    monkeypatch.setattr(
        "opencobalt.cli._listener_has_live_ui_launcher_ancestor", lambda pid: False
    )
    monkeypatch.setattr(
        "opencobalt.cli._opencobalt_listener_is_healthy", lambda port, label: False
    )

    def unexpected_kill(pid, signal_number):
        raise AssertionError(f"must not kill changed listener pid {pid}")

    monkeypatch.setattr("os.kill", unexpected_kill)

    assert _reclaim_stale_opencobalt_listener(8000, "API") is False


def test_active_launcher_owned_listener_is_never_reclaimed(monkeypatch) -> None:
    monkeypatch.setattr(
        "opencobalt.cli._opencobalt_owned_listener",
        lambda port, label: (4242, "node /repo/OpenCobalt/ui/node_modules/.bin/vite"),
    )
    monkeypatch.setattr(
        "opencobalt.cli._listener_has_live_ui_launcher_ancestor", lambda pid: True
    )

    def unexpected_kill(pid, signal_number):
        raise AssertionError(f"must not kill active listener pid {pid}")

    monkeypatch.setattr("os.kill", unexpected_kill)

    assert _reclaim_stale_opencobalt_listener(5173, "UI") is False


def test_ui_refuses_an_occupied_api_port_before_starting_children(
    tmp_path, monkeypatch
) -> None:
    ui_dir = tmp_path / "ui"
    (ui_dir / "node_modules" / "lucide-react").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shutil.which", lambda executable: f"/test/{executable}")

    def unexpected_child(*args, **kwargs):
        raise AssertionError("a child process started before port validation")

    monkeypatch.setattr(subprocess, "Popen", unexpected_child)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        api_port = occupied.getsockname()[1]
        result = CliRunner().invoke(
            app,
            ["ui", "--no-browser", "--port", "5197", "--api-port", str(api_port)],
            color=False,
        )

    assert result.exit_code == 1
    assert f"API port {api_port} is already in use" in result.output
    assert "a child process started" not in result.output


def test_ui_reports_api_child_failure_after_a_readiness_connection_reset(
    tmp_path, monkeypatch
) -> None:
    ui_dir = tmp_path / "ui"
    (ui_dir / "node_modules" / "lucide-react").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shutil.which", lambda executable: f"/test/{executable}")
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionResetError("reset")),
    )

    class FakeProcess:
        def __init__(self, returncode):
            self.returncode = returncode
            self.terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    api_process = FakeProcess(1)
    vite_process = FakeProcess(None)
    processes = iter([api_process, vite_process])
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: next(processes))

    result = CliRunner().invoke(
        app,
        [
            "ui",
            "--no-browser",
            "--port",
            str(_unused_loopback_port()),
            "--api-port",
            str(_unused_loopback_port()),
        ],
        color=False,
    )

    assert result.exit_code == 1
    assert "API server failed to start" in result.output
    assert "ConnectionResetError" not in result.output
    assert vite_process.terminated is True


def test_ui_retries_a_transient_readiness_reset_before_waiting(
    tmp_path, monkeypatch
) -> None:
    ui_dir = tmp_path / "ui"
    (ui_dir / "node_modules" / "lucide-react").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shutil.which", lambda executable: f"/test/{executable}")
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    attempts = 0

    class FakeResponse:
        def close(self):
            return None

    def probe(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionResetError("transient reset")
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", probe)

    class RunningProcess:
        def __init__(self, interrupt_after_polls=None):
            self.interrupt_after_polls = interrupt_after_polls
            self.poll_count = 0
            self.interrupted = False
            self.terminated = False
            self.waited = False

        def poll(self):
            self.poll_count += 1
            if (
                self.interrupt_after_polls is not None
                and self.poll_count >= self.interrupt_after_polls
                and not self.interrupted
            ):
                self.interrupted = True
                raise KeyboardInterrupt
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            self.waited = True
            return 0

        def kill(self):
            self.terminated = True

    api_process = RunningProcess(interrupt_after_polls=3)
    vite_process = RunningProcess()
    processes = iter([api_process, vite_process])
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: next(processes))

    result = CliRunner().invoke(
        app,
        [
            "ui",
            "--no-browser",
            "--port",
            str(_unused_loopback_port()),
            "--api-port",
            str(_unused_loopback_port()),
        ],
        color=False,
    )

    assert result.exit_code == 0
    assert attempts == 2
    assert api_process.terminated is True
    assert vite_process.terminated is True
    assert api_process.waited is True
    assert vite_process.waited is True


def test_ui_stops_api_when_vite_exits_after_readiness(tmp_path, monkeypatch) -> None:
    ui_dir = tmp_path / "ui"
    (ui_dir / "node_modules" / "lucide-react").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shutil.which", lambda executable: f"/test/{executable}")
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    class FakeResponse:
        def close(self):
            return None

    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())

    class FakeProcess:
        def __init__(self, poll_results):
            self.poll_results = iter(poll_results)
            self.last = None
            self.terminated = False
            self.waited = False

        def poll(self):
            self.last = next(self.poll_results, self.last)
            return self.last

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            self.waited = True
            return 0

        def kill(self):
            self.terminated = True

    api_process = FakeProcess([None, None, None])
    vite_process = FakeProcess([None, 1])
    processes = iter([api_process, vite_process])
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: next(processes))

    result = CliRunner().invoke(
        app,
        [
            "ui",
            "--no-browser",
            "--port",
            str(_unused_loopback_port()),
            "--api-port",
            str(_unused_loopback_port()),
        ],
        color=False,
    )

    assert result.exit_code == 1
    assert "UI server stopped unexpectedly" in result.output
    assert api_process.terminated is True
    assert api_process.waited is True
    assert vite_process.waited is True


def test_ui_keeps_waiting_while_the_api_process_is_alive_past_ten_seconds(
    tmp_path, monkeypatch
) -> None:
    ui_dir = tmp_path / "ui"
    (ui_dir / "node_modules" / "lucide-react").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shutil.which", lambda executable: f"/test/{executable}")
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    clock = {"now": 0.0}
    attempts = {"n": 0}

    class FakeResponse:
        def close(self):
            return None

    def probe(url, *args, **kwargs):
        assert "/api/ready" in url
        attempts["n"] += 1
        clock["now"] = float(attempts["n"])
        if attempts["n"] < 12:
            raise ConnectionResetError("still importing")
        return FakeResponse()

    monkeypatch.setattr("time.monotonic", lambda: clock["now"])
    monkeypatch.setattr(urllib.request, "urlopen", probe)

    class RunningProcess:
        def __init__(self, interrupt_after_polls=None):
            self.interrupt_after_polls = interrupt_after_polls
            self.poll_count = 0
            self.interrupted = False
            self.terminated = False
            self.waited = False

        def poll(self):
            self.poll_count += 1
            if (
                self.interrupt_after_polls is not None
                and self.poll_count >= self.interrupt_after_polls
                and not self.interrupted
            ):
                self.interrupted = True
                raise KeyboardInterrupt
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            self.waited = True
            return 0

        def kill(self):
            self.terminated = True

    api_process = RunningProcess(interrupt_after_polls=20)
    vite_process = RunningProcess()
    processes = iter([api_process, vite_process])
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: next(processes))

    result = CliRunner().invoke(
        app,
        [
            "ui",
            "--no-browser",
            "--port",
            str(_unused_loopback_port()),
            "--api-port",
            str(_unused_loopback_port()),
        ],
        color=False,
    )

    assert result.exit_code == 0
    assert "did not become ready within 10 seconds" not in result.output
    assert "API ready after" in result.output
    assert api_process.terminated is True
