import pytest

from opencobalt.integrations import REGISTRY, get_integration, list_integrations
from opencobalt.integrations.aider_integration import AiderIntegration
from opencobalt.integrations.cursor_integration import CursorIntegration
from opencobalt.integrations.ollama_integration import OllamaIntegration


def test_registry_has_current_canonical_integrations():
    assert len(REGISTRY) == 8


def test_registry_contains_aider_and_ollama():
    assert "aider" in REGISTRY
    assert "ollama" in REGISTRY


def test_registry_contains_canonical_integrations_only():
    assert set(REGISTRY) == {
        "aider",
        "claude-code",
        "context7",
        "cursor",
        "github-cli",
        "google-antigravity",
        "obsidian",
        "ollama",
    }
    assert "gemini-cli" not in REGISTRY
    assert "antigravity-cli" not in REGISTRY


def test_ollama_integration_name():
    integration = REGISTRY["ollama"]
    assert integration.name == "ollama"


def test_aider_integration_name():
    integration = REGISTRY["aider"]
    assert integration.name == "aider"


def test_aider_install_check_returns_bool():
    integration = AiderIntegration()
    result = integration.install_check()
    assert isinstance(result, bool)


def test_ollama_install_check_returns_bool():
    integration = OllamaIntegration()
    result = integration.install_check()
    assert isinstance(result, bool)


def test_cursor_integration_remains_editor_awareness_not_runtime_claim(monkeypatch):
    monkeypatch.setattr("opencobalt.integrations.cursor_integration.shutil.which", lambda command: None)
    monkeypatch.setattr(
        "opencobalt.integrations.cursor_integration._default_app_paths",
        lambda: (),
    )
    integration = CursorIntegration()

    assert integration.install_check() is False
    assert integration.integration_status() == "stub"
    assert "runtime adapter" in integration.invoke("plan UI work")
    assert "stub" in integration.invoke("plan UI work")


def test_list_integrations_returns_canonical_profiles():
    profiles = list_integrations()
    assert len(profiles) == len(REGISTRY)
    names = {profile.name for profile in profiles}
    assert "google-antigravity" in names
    assert "gemini-cli" not in names
    assert "antigravity-cli" not in names


def test_list_integrations_profiles_have_required_fields():
    for profile in list_integrations():
        assert profile.name
        assert profile.description
        assert profile.source_url
        assert isinstance(profile.installed, bool)


def test_get_integration_returns_none_for_unknown():
    assert get_integration("does-not-exist") is None


def test_get_integration_returns_correct_instance():
    integration = get_integration("aider")
    assert integration is not None
    assert integration.name == "aider"


def test_antigravity_compatibility_alias_resolves_to_canonical():
    integration = get_integration("antigravity-cli")
    assert integration is not None
    assert integration.name == "google-antigravity"


@pytest.mark.parametrize("alias", ["gemini-cli", "gemini_cli", "google-gemini-cli"])
def test_legacy_gemini_aliases_resolve_with_deprecation_warning(alias):
    with pytest.warns(DeprecationWarning, match="Gemini CLI integration is legacy"):
        integration = get_integration(alias)
    assert integration is not None
    assert integration.name == "google-antigravity"


def test_aider_invoke_returns_string():
    integration = AiderIntegration()
    result = integration.invoke("write a test")
    assert isinstance(result, str)
    assert "stub" in result


def test_ollama_invoke_truncates_long_task():
    integration = OllamaIntegration()
    long_task = "x" * 100
    result = integration.invoke(long_task)
    assert isinstance(result, str)
    assert "stub" in result
    # task portion should be truncated to 60 chars
    assert "x" * 61 not in result
