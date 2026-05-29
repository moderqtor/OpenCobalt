"""Tests for the config module."""
from opencobalt.core.config import Config


def test_config_get_default(tmp_path):
    cfg = Config(tmp_path / "ledger.db")
    assert cfg.get("missing_key") is None
    assert cfg.get("missing_key", "fallback") == "fallback"


def test_config_set_and_get(tmp_path):
    cfg = Config(tmp_path / "ledger.db")
    cfg.set("api_enabled", "true")
    assert cfg.get("api_enabled") == "true"


def test_config_overwrite(tmp_path):
    cfg = Config(tmp_path / "ledger.db")
    cfg.set("mode", "cheap")
    cfg.set("mode", "frontier")
    assert cfg.get("mode") == "frontier"


def test_config_list_all(tmp_path):
    cfg = Config(tmp_path / "ledger.db")
    cfg.set("key1", "val1")
    cfg.set("key2", "val2")
    result = cfg.list_all()
    assert result == {"key1": "val1", "key2": "val2"}


def test_config_delete(tmp_path):
    cfg = Config(tmp_path / "ledger.db")
    cfg.set("temp", "value")
    cfg.delete("temp")
    assert cfg.get("temp") is None
