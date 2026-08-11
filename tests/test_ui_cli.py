"""Release-facing tests for the single-command local UI launcher."""

from __future__ import annotations

import socket
import subprocess
import urllib.request

from typer.testing import CliRunner

from opencobalt.cli import app


def _unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


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

        def wait(self):
            return self.returncode

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
        def __init__(self, interrupt_on_wait=False):
            self.interrupt_on_wait = interrupt_on_wait
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self):
            if self.interrupt_on_wait:
                raise KeyboardInterrupt
            return 0

    api_process = RunningProcess(interrupt_on_wait=True)
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
