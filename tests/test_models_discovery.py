from unittest.mock import MagicMock, patch

from opencobalt.core.models_discovery import (
    ModelInfo,
    discover_models,
    is_ollama_available,
    worker_tier_models,
)

_SAMPLE_OUTPUT = (
    "NAME              ID              SIZE      MODIFIED\n"
    "llama3:latest     365c0bd3c000    4.7 GB    6 weeks ago\n"
    "mistral:latest    6577803aa9a0    4.4 GB    6 weeks ago\n"
)


def test_model_info_fields():
    mi = ModelInfo(name="llama3:latest", model_id="abc123", size="4.7 GB")
    assert mi.name == "llama3:latest"
    assert mi.model_id == "abc123"


def test_discover_models_parses_output():
    mock = MagicMock(returncode=0, stdout=_SAMPLE_OUTPUT)
    with patch("subprocess.run", return_value=mock):
        models = discover_models()
    assert len(models) == 2
    assert models[0].name == "llama3:latest"
    assert models[1].name == "mistral:latest"


def test_discover_models_fallback_no_ollama():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        models = discover_models()
    assert models == []


def test_discover_models_fallback_nonzero_exit():
    mock = MagicMock(returncode=1, stdout="")
    with patch("subprocess.run", return_value=mock):
        models = discover_models()
    assert models == []


def test_discover_models_timeout():
    import subprocess
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ollama", 10)):
        models = discover_models()
    assert models == []


def test_is_ollama_available_true():
    mock = MagicMock(returncode=0)
    with patch("subprocess.run", return_value=mock):
        assert is_ollama_available() is True


def test_is_ollama_available_false():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        assert is_ollama_available() is False


def test_worker_tier_models_passthrough():
    models = [ModelInfo("llama3:latest", "abc", "4.7 GB")]
    assert worker_tier_models(models) == models
