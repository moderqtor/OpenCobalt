"""Tests for the OpenCobalt agents package."""

from opencobalt.agents.base_agent import BaseAgent
from opencobalt.agents.code_reviewer import CodeReviewerAgent
from opencobalt.agents.context_builder import ContextBuilderAgent
from opencobalt.agents.registry import REGISTRY, get_agent, list_agents
from opencobalt.agents.summarizer import SummarizerAgent
from opencobalt.agents.tagger import TaggerAgent


def test_registry_has_four_agents():
    assert len(REGISTRY) == 4


def test_list_agents_returns_four_profiles():
    profiles = list_agents()
    assert len(profiles) == 4


def test_list_agents_sorted_by_name():
    profiles = list_agents()
    names = [p.name for p in profiles]
    assert names == sorted(names)


def test_get_agent_summarizer():
    agent = get_agent("summarizer")
    assert agent is not None
    assert isinstance(agent, SummarizerAgent)


def test_get_agent_tagger():
    agent = get_agent("tagger")
    assert agent is not None
    assert isinstance(agent, TaggerAgent)


def test_get_agent_code_reviewer():
    agent = get_agent("code-reviewer")
    assert agent is not None
    assert isinstance(agent, CodeReviewerAgent)


def test_get_agent_context_builder():
    agent = get_agent("context-builder")
    assert agent is not None
    assert isinstance(agent, ContextBuilderAgent)


def test_get_agent_unknown_returns_none():
    assert get_agent("nonexistent-agent") is None


# -- tier checks --

def test_summarizer_tier_is_worker():
    assert get_agent("summarizer").profile.tier == "worker"


def test_tagger_tier_is_worker():
    assert get_agent("tagger").profile.tier == "worker"


def test_code_reviewer_tier_is_manager():
    assert get_agent("code-reviewer").profile.tier == "manager"


def test_context_builder_tier_is_worker():
    assert get_agent("context-builder").profile.tier == "worker"


# -- dry run --

def test_summarizer_dry_run():
    agent = get_agent("summarizer")
    result = agent.run("test task", dry_run=True)
    assert result == "[dry-run] summarizer would process task via Ollama"


def test_tagger_dry_run():
    agent = get_agent("tagger")
    result = agent.run("test task", dry_run=True)
    assert result == "[dry-run] tagger would process task via Ollama"


def test_code_reviewer_dry_run():
    agent = get_agent("code-reviewer")
    result = agent.run("review this", dry_run=True)
    assert result.startswith("[dry-run]")


def test_context_builder_dry_run():
    agent = get_agent("context-builder")
    result = agent.run("build context", dry_run=True)
    assert result.startswith("[dry-run]")


# -- live run output --

def test_summarizer_run_returns_non_empty():
    agent = get_agent("summarizer")
    result = agent.run("summarize this document")
    assert len(result) > 0
    assert "stub" in result


def test_tagger_run_returns_non_empty():
    agent = get_agent("tagger")
    result = agent.run("tag this document")
    assert len(result) > 0
    assert "stub" in result


def test_code_reviewer_run_returns_non_empty():
    agent = get_agent("code-reviewer")
    result = agent.run("review this")
    assert len(result) > 0


def test_code_reviewer_run_mentions_escalation():
    agent = get_agent("code-reviewer")
    result = agent.run("review this")
    assert "escalat" in result.lower()


def test_context_builder_run_returns_non_empty():
    agent = get_agent("context-builder")
    result = agent.run("build context")
    assert len(result) > 0


def test_context_builder_run_is_string():
    agent = get_agent("context-builder")
    result = agent.run("build context")
    assert isinstance(result, str)


# -- base class properties --

def test_agent_name_property():
    agent = get_agent("summarizer")
    assert agent.name == "summarizer"


def test_agent_tier_property():
    agent = get_agent("code-reviewer")
    assert agent.tier == "manager"


def test_agent_capabilities_property():
    agent = get_agent("summarizer")
    assert "summarization" in agent.capabilities


def test_all_agents_are_base_agent_instances():
    for agent in REGISTRY.values():
        assert isinstance(agent, BaseAgent)
