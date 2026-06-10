import pytest

from opencobalt.core.subagent_registry import SubagentRegistry, SubagentSpec


def test_registry_has_default_library():
    r = SubagentRegistry()
    assert len(r.list_all()) == 17


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
    assert spec.tool == "google-antigravity"


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
        assert spec.risk_ceiling in ("green", "yellow", "red", "black")
        assert spec.permission_scope in ("read", "write", "execute")
        assert spec.output_contract in ("report", "artifact", "receipt", "prose")


def test_register_custom_subagent():
    r = SubagentRegistry()
    r.register(
        SubagentSpec(
            agent_id="custom-checker",
            specialization="custom checks",
            tier="worker",
            tool="ollama",
            task_types=["custom"],
        )
    )
    assert r.get("custom-checker") is not None
    resolved = r.get_for_task_type("custom")
    assert resolved is not None
    assert resolved.agent_id == "custom-checker"


def test_register_duplicate_id_rejected():
    r = SubagentRegistry()
    with pytest.raises(ValueError):
        r.register(
            SubagentSpec(
                agent_id="impl-agent",
                specialization="dup",
                tier="worker",
                tool="ollama",
                task_types=["dup"],
            )
        )


def test_register_invalid_ceiling_rejected():
    r = SubagentRegistry()
    with pytest.raises(ValueError):
        r.register(
            SubagentSpec(
                agent_id="bad-risk",
                specialization="bad",
                tier="worker",
                tool="ollama",
                task_types=["bad"],
                risk_ceiling="purple",
            )
        )


def test_registry_instances_are_isolated():
    a = SubagentRegistry()
    b = SubagentRegistry()
    a.register(
        SubagentSpec(
            agent_id="only-in-a",
            specialization="isolation check",
            tier="worker",
            tool="ollama",
            task_types=["isolated"],
        )
    )
    assert b.get("only-in-a") is None


def test_empty_registry_without_defaults():
    r = SubagentRegistry(include_defaults=False)
    assert r.list_all() == []
