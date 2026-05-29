from opencobalt.core.router import route_task


def test_route_summarize_is_worker_ollama():
    d = route_task("summarize this log file")
    assert d.recommended_tool == "ollama"
    assert d.tier == "worker"


def test_route_architecture_is_executive():
    d = route_task("design the architecture for the new event spine module")
    assert d.tier == "executive"
    assert d.recommended_tool in ("claude-code", "gemini-cli")


def test_route_tests_goes_to_manager_or_executive():
    d = route_task("run tests and validate the ledger module")
    assert d.recommended_tool in ("codex-cli", "claude-code")
    assert d.tier in ("manager", "executive")


def test_route_ui_component_goes_to_cursor():
    d = route_task("update the React component styles in the dashboard")
    assert d.recommended_tool == "cursor"


def test_route_long_context_goes_to_gemini_or_claude():
    d = route_task("read the entire codebase and find all unused imports")
    assert d.recommended_tool in ("gemini-cli", "claude-code")


def test_route_security_is_never_ollama():
    d = route_task("do a security audit of the authentication module")
    assert d.recommended_tool != "ollama"


def test_route_decision_has_reasoning():
    d = route_task("extract the key entities from this document")
    assert len(d.reasoning) > 0


def test_route_decision_has_score():
    d = route_task("build a CLI command for the status view")
    assert isinstance(d.score, int)
    assert d.score >= 0


def test_route_rough_draft_goes_to_ollama():
    d = route_task("write a rough draft summary of this file")
    assert d.recommended_tool == "ollama"
    assert d.tier == "worker"


def test_route_employer_facing_is_not_ollama():
    d = route_task("write the employer-facing README section")
    assert d.recommended_tool != "ollama"
