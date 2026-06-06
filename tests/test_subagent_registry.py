from opencobalt.core.subagent_registry import SubagentRegistry


def test_registry_has_six_agents():
    r = SubagentRegistry()
    assert len(r.list_all()) == 6


def test_lookup_by_task_type_impl():
    r = SubagentRegistry()
    spec = r.get_for_task_type("impl")
    assert spec is not None
    assert spec.agent_id == "impl-agent"
    assert spec.tool == "claude-code"


def test_lookup_by_task_type_tests():
    r = SubagentRegistry()
    spec = r.get_for_task_type("tests")
    assert spec is not None
    assert spec.agent_id == "test-gen"
    assert spec.tool == "codex-cli"


def test_lookup_by_task_type_analyze():
    r = SubagentRegistry()
    spec = r.get_for_task_type("analyze")
    assert spec is not None
    assert spec.tool == "gemini-cli"


def test_lookup_unknown_type_returns_none():
    r = SubagentRegistry()
    assert r.get_for_task_type("nonexistent") is None


def test_lookup_by_agent_id():
    r = SubagentRegistry()
    spec = r.get("summarizer")
    assert spec is not None
    assert spec.tool == "ollama"


def test_spec_has_required_fields():
    r = SubagentRegistry()
    for spec in r.list_all():
        assert spec.agent_id
        assert spec.specialization
        assert spec.tier in ("executive", "manager", "worker")
        assert spec.tool
        assert spec.task_types
