from opencobalt.integrations import REGISTRY, get_integration, list_integrations
from opencobalt.integrations.aider_integration import AiderIntegration
from opencobalt.integrations.ollama_integration import OllamaIntegration


def test_registry_has_seven_integrations():
    assert len(REGISTRY) == 7


def test_registry_contains_aider_and_ollama():
    assert "aider" in REGISTRY
    assert "ollama" in REGISTRY


def test_registry_contains_all_integrations():
    assert "claude-code" in REGISTRY
    assert "gemini-cli" in REGISTRY
    assert "antigravity-cli" in REGISTRY
    assert "cursor" in REGISTRY
    assert "context7" in REGISTRY


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


def test_list_integrations_returns_seven_profiles():
    profiles = list_integrations()
    assert len(profiles) == 7


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
