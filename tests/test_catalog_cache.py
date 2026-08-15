"""Catalog TTL cache and Antigravity discover_models reuse."""

from __future__ import annotations

import time

from opencobalt.personal_ai.antigravity import AntigravityChatProvider
from opencobalt.personal_ai.catalog_cache import TtlCache
from opencobalt.personal_ai.providers import ProviderRequest
from tests.test_antigravity_research import IsolatedAgyAdapter, _catalog_stdout
from tests.test_personal_ai_providers import FakeEngine, _outcome


def test_ttl_cache_expires_errors_faster_than_successes():
    cache = TtlCache[str](ttl_seconds=0.3, error_ttl_seconds=0.05)
    cache.store("ok", is_error=False)
    assert cache.get() is not None
    cache.store("boom", is_error=True)
    assert cache.get() is not None
    time.sleep(0.08)
    assert cache.get() is None
    cache.store("ok", is_error=False)
    time.sleep(0.08)
    assert cache.get() is not None
    cache.invalidate()
    assert cache.get() is None


def test_antigravity_second_discover_models_is_a_cache_hit():
    engine = FakeEngine(
        _outcome(stdout=_catalog_stdout("claude-sonnet-4-6")),
        _outcome(stdout=_catalog_stdout("gemini-3-pro")),
    )
    provider = AntigravityChatProvider(engine, IsolatedAgyAdapter())

    first = provider.discover_models()
    second = provider.discover_models()
    refreshed = provider.discover_models(refresh=True)

    assert first.cache_hit is False
    assert first.cache_source == "live_discovery"
    assert [model.model_id for model in first.models] == ["claude-sonnet-4-6"]
    assert second.cache_hit is True
    assert second.cache_source == "cache"
    assert [model.model_id for model in second.models] == ["claude-sonnet-4-6"]
    assert refreshed.cache_hit is False
    assert [model.model_id for model in refreshed.models] == ["gemini-3-pro"]
    assert len(engine.calls) == 2


def test_antigravity_execute_does_not_launch_a_second_catalog_command():
    engine = FakeEngine(
        _outcome(stdout=_catalog_stdout("claude-sonnet-4-6")),
        _outcome(stdout='{"status":"SUCCESS","response":"ok"}'),
    )
    provider = AntigravityChatProvider(engine, IsolatedAgyAdapter())
    provider.discover_models()
    result = provider.execute(
        ProviderRequest(message="hello", model_id="claude-sonnet-4-6")
    )
    assert result.status == "complete"
    catalog_calls = [
        call for call in engine.calls if "catalog" in call[0].casefold()
    ]
    assert len(catalog_calls) == 1
    assert len(engine.calls) == 2
