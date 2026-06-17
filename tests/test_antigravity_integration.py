import subprocess

import pytest

from opencobalt.integrations import REGISTRY, get_integration
from opencobalt.integrations.antigravity_integration import (
    ANTIGRAVITY_CAPABILITIES,
    AntigravityIntegration,
    build_antigravity_command,
    discover_antigravity_runtime,
)


class _Completed:
    def __init__(self, args, returncode=0, stdout="", stderr=""):
        self.args = args
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_antigravity_metadata_is_canonical():
    integration = AntigravityIntegration()
    assert integration.name == "google-antigravity"
    assert integration.display_name == "Google Antigravity CLI"
    assert integration.command == "agy"
    assert integration.vendor == "google"
    assert integration.kind == "agent_runtime"
    assert integration.status == "primary"
    assert "agent-runtime" in integration.capabilities


def test_antigravity_capabilities_do_not_fabricate_unknowns():
    assert ANTIGRAVITY_CAPABILITIES["agent_runtime"]["supported"] is True
    assert ANTIGRAVITY_CAPABILITIES["multi_agent_orchestration"]["source"] == "unknown"
    assert ANTIGRAVITY_CAPABILITIES["browser_verification"]["source"] == "unknown"
    assert ANTIGRAVITY_CAPABILITIES["skills_hooks_subagents"]["source"] == "unknown"


def test_install_check_uses_agy(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda command: "/usr/local/bin/agy" if command == "agy" else None)
    assert AntigravityIntegration().install_check() is True


def test_invoke_is_boundary_stub_without_task_echo(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("Antigravity integration invoke must not start a subprocess")

    monkeypatch.setattr(subprocess, "run", explode)
    result = AntigravityIntegration().invoke("private task text")

    assert result.startswith("[blocked]")
    assert "--runtime google-antigravity" in result
    assert "private task text" not in result
    assert "stub" in result


def test_missing_agy_detection_is_clean(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda command: None)
    result = discover_antigravity_runtime()
    assert result["installed"] is False
    assert result["path"] is None
    assert result["version"]["ok"] is False
    assert result["help"]["ok"] is False


def _discover_with_help(monkeypatch, help_text: str):
    monkeypatch.setattr("shutil.which", lambda command: "/usr/local/bin/agy" if command == "agy" else None)

    def fake_run(args, **kwargs):
        if args == ["agy", "--version"]:
            return _Completed(args, stdout="1.0.6\n")
        if args == ["agy", "--help"]:
            return _Completed(args, stdout=help_text)
        raise AssertionError(args)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return discover_antigravity_runtime()


def test_runtime_discovery_parses_supported_help_evidence(monkeypatch):
    result = _discover_with_help(
        monkeypatch,
        "--print\n--model\nplugin Manage plugins\n--sandbox\n",
    )
    assert result["installed"] is True
    assert result["version"]["value"] == "1.0.6"
    assert result["capabilities"]["non_interactive_mode"]["source"] == "runtime_discovered"
    assert result["capabilities"]["non_interactive_print"]["source"] == "runtime_discovered"
    assert result["capabilities"]["model_selection"]["source"] == "runtime_discovered"
    assert result["capabilities"]["plugin_support"]["source"] == "runtime_discovered"
    assert result["capabilities"]["terminal_sandbox"]["source"] == "runtime_discovered"
    assert result["capabilities"]["sandbox_mode"]["source"] == "runtime_discovered"
    assert result["capabilities"]["browser_verification"]["source"] == "unknown"


def test_help_parsing_detects_print_flag(monkeypatch):
    result = _discover_with_help(monkeypatch, "Usage: agy [options]\n  -p, --print <prompt>\n")
    capability = result["capabilities"]["non_interactive_print"]
    assert capability["supported"] is True
    assert capability["source"] == "runtime_discovered"
    assert capability["evidence"] == "--print found in agy help"


def test_help_parsing_detects_model_flag(monkeypatch):
    result = _discover_with_help(monkeypatch, "Usage: agy --model <model> [prompt]\n")
    capability = result["capabilities"]["model_selection"]
    assert capability["supported"] is True
    assert capability["source"] == "runtime_discovered"
    assert capability["evidence"] == "--model found in agy help"


def test_help_parsing_detects_plugin_support(monkeypatch):
    result = _discover_with_help(monkeypatch, "Commands:\n  plugins   Manage installed plugins\n")
    capability = result["capabilities"]["plugin_support"]
    assert capability["supported"] is True
    assert capability["source"] == "runtime_discovered"
    assert capability["evidence"] == "plugin found in agy help"


def test_help_parsing_detects_sandbox_flag(monkeypatch):
    result = _discover_with_help(monkeypatch, "Options:\n  --sandbox    Run with terminal restrictions\n")
    capability = result["capabilities"]["sandbox_mode"]
    assert capability["supported"] is True
    assert capability["source"] == "runtime_discovered"
    assert capability["evidence"] == "--sandbox found in agy help"


def test_help_parsing_detects_unsafe_permission_bypass(monkeypatch):
    result = _discover_with_help(
        monkeypatch,
        "Options:\n  --dangerously-skip-permissions    Auto-approve permission requests\n",
    )
    capability = result["capabilities"]["unsafe_skip_permissions"]
    assert capability["supported"] is True
    assert capability["source"] == "runtime_discovered"
    assert capability["evidence"] == "--dangerously-skip-permissions found in agy help"
    assert capability["allowed_by_default"] is False
    assert capability["risk"] == "red"


def test_unknowns_stay_unknown_with_generic_antigravity_help(monkeypatch):
    result = _discover_with_help(
        monkeypatch,
        "Google Antigravity CLI\nUse agy to work with your local project.\n",
    )
    capabilities = result["capabilities"]
    assert capabilities["browser_verification"]["source"] == "unknown"
    assert capabilities["screenshot_capture"]["source"] == "unknown"
    assert capabilities["sqlite_conversation_schema"]["source"] == "unknown"
    assert capabilities["subagent_protocol"]["source"] == "unknown"
    assert capabilities["skills_hooks_subagents"]["source"] == "unknown"


def test_non_interactive_print_command_construction():
    assert build_antigravity_command("hello") == ["agy", "--print", "hello"]


def test_model_selection_command_construction():
    assert build_antigravity_command("hello", model="gemini-pro") == [
        "agy",
        "--model",
        "gemini-pro",
        "--print",
        "hello",
    ]


def test_sandbox_command_construction():
    assert build_antigravity_command("hello", sandbox=True) == ["agy", "--sandbox", "--print", "hello"]


def test_dangerous_skip_permissions_forbidden_by_default():
    command = build_antigravity_command("hello", dangerously_skip_permissions=True)
    assert "--dangerously-skip-permissions" not in command


def test_dangerous_skip_permissions_requires_explicit_unsafe_override():
    with pytest.warns(RuntimeWarning, match="dangerously-skip-permissions"):
        command = build_antigravity_command(
            "hello",
            dangerously_skip_permissions=True,
            allow_dangerously_skip_permissions=True,
        )
    assert command == ["agy", "--dangerously-skip-permissions", "--print", "hello"]


def test_help_failure_is_handled_gracefully(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda command: "/usr/local/bin/agy" if command == "agy" else None)

    def fake_run(args, **kwargs):
        if args == ["agy", "--version"]:
            return _Completed(args, stdout="1.0.6\n")
        if args == ["agy", "--help"]:
            return _Completed(args, returncode=2, stderr="bad help")
        raise AssertionError(args)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = discover_antigravity_runtime()
    assert result["installed"] is True
    assert result["help"]["ok"] is False
    assert result["capabilities"]["non_interactive_mode"]["source"] == "unknown"


def test_legacy_gemini_alias_resolves_with_deprecation_warning():
    assert "google-antigravity" in REGISTRY
    with pytest.warns(DeprecationWarning, match="Gemini CLI integration is legacy"):
        integration = get_integration("gemini-cli")
    assert integration is not None
    assert integration.name == "google-antigravity"


@pytest.mark.parametrize("alias", ["gemini_cli", "google-gemini-cli"])
def test_legacy_gemini_alias_variants_resolve(alias):
    with pytest.warns(DeprecationWarning):
        integration = get_integration(alias)
    assert integration is not None
    assert integration.name == "google-antigravity"
