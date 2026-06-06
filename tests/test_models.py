from opencobalt.core.models import (
    AgentProfile,
    ContextPack,
    DesignBrief,
    MemoryRecord,
    MultiRouteDecision,
    OrchestrationResult,
    RouteDecision,
    SessionEvent,
    SubTask,
    ToolRun,
    VerificationResult,
)


def test_session_event_defaults():
    e = SessionEvent(project="proj", source="cli", event_type="start", summary="started")
    assert e.id
    assert e.timestamp
    assert e.project == "proj"
    assert e.metadata == {}


def test_route_decision_tiers():
    for tier in ("executive", "manager", "worker"):
        rd = RouteDecision(
            task="do a thing",
            recommended_tool="claude-code",
            score=80,
            reasoning="matched",
            tier=tier,
        )
        assert rd.tier == tier


def test_verification_result_passed():
    vr = VerificationResult(command="pytest", exit_code=0, passed=True, output_summary="5 passed")
    assert vr.passed is True


def test_memory_record_fields():
    mr = MemoryRecord(project="p", namespace="ideas", content="a thought", source="cli")
    assert mr.id
    assert mr.namespace == "ideas"


def test_context_pack_defaults():
    cp = ContextPack(project="p", content="text", token_estimate=100)
    assert cp.sources == []


def test_agent_profile():
    ap = AgentProfile(
        agent_id="a1", name="Claude", tier="executive",
        capabilities=["code"], task_types=["impl"],
    )
    assert ap.requires_api_key is False


def test_design_brief_defaults():
    db = DesignBrief(project="p", description="dark UI")
    assert db.design_tokens == {}
    assert db.anti_slop_rules == []


def test_tool_run():
    tr = ToolRun(session_id="s1", tool="claude-code", command="implement auth")
    assert tr.exit_code is None


def test_subtask_defaults():
    st = SubTask(task_type="impl", prompt="build it", preferred_tool="claude-code")
    assert st.id
    assert st.preferred_agent is None


def test_orchestration_result_success_flag():
    st = SubTask(task_type="impl", prompt="build it", preferred_tool="claude-code")
    r = OrchestrationResult(
        task="build auth",
        subtasks=[st],
        outputs={st.id: "done"},
        synthesis="merged",
        elapsed_s=1.2,
        success=True,
    )
    assert r.success
    assert r.errors == []


def test_multi_route_decision_fields():
    st = SubTask(task_type="tests", prompt="write tests", preferred_tool="codex-cli")
    d = MultiRouteDecision(
        task="build auth",
        subtasks=[st],
        tools_used=["codex-cli"],
        result_id="abc",
    )
    assert d.id
    assert d.timestamp
    assert d.tools_used == ["codex-cli"]
