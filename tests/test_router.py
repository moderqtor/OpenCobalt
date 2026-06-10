from opencobalt.core.router import route_task


def test_route_summarize_is_worker_ollama():
    d = route_task("summarize this log file")
    assert d.recommended_tool == "ollama"
    assert d.tier == "worker"


def test_route_architecture_is_executive():
    d = route_task("design the architecture for the new event spine module")
    assert d.tier == "executive"
    assert d.recommended_tool in ("claude-code", "google-antigravity")


def test_route_tests_goes_to_manager_or_executive():
    d = route_task("run tests and validate the ledger module")
    assert d.recommended_tool in ("codex-cli", "claude-code")
    assert d.tier in ("manager", "executive")


def test_route_ui_component_goes_to_cursor():
    d = route_task("update the React component styles in the dashboard")
    assert d.recommended_tool == "cursor"


def test_route_long_context_goes_to_antigravity_or_claude():
    d = route_task("read the entire codebase and find all unused imports")
    assert d.recommended_tool in ("google-antigravity", "claude-code")


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


def test_route_browser_validation_prefers_antigravity():
    d = route_task("validate the dashboard in a browser and record artifacts")
    assert d.recommended_tool == "google-antigravity"
    assert d.metadata["runtime"] == "google-antigravity"
    assert d.metadata["runtime_command"] == "agy"
    assert d.metadata["approval_required"] is True


def test_route_ui_screenshot_prefers_antigravity():
    d = route_task("capture screenshots of the React UI and inspect visual regressions")
    assert d.recommended_tool == "google-antigravity"


def test_route_multi_agent_prefers_antigravity():
    d = route_task("coordinate a multi-agent implementation with browser validation")
    assert d.recommended_tool == "google-antigravity"


def test_route_artifact_heavy_workflow_prefers_antigravity():
    d = route_task("produce a plan, diff, test output, screenshots, and an artifact report")
    assert d.recommended_tool == "google-antigravity"


def test_route_tiny_single_file_edit_does_not_select_antigravity():
    d = route_task("make a tiny single-file deterministic edit to fix a typo")
    assert d.recommended_tool != "google-antigravity"


def test_route_cheap_summary_does_not_select_antigravity():
    d = route_task("cheap summary of this note")
    assert d.recommended_tool == "ollama"


def test_route_metadata_distinguishes_runtime_and_model_policy():
    d = route_task("validate browser screenshots for the dashboard")
    assert d.metadata["runtime"] == d.recommended_tool
    assert "model_policy" in d.metadata
    assert "risk_level" in d.metadata


def test_antigravity_credential_environment_tasks_require_red_approval():
    d = route_task("use antigravity to inspect .env tokens SSH keys and browser profiles")
    assert d.recommended_tool == "google-antigravity"
    assert d.metadata["risk_level"] == "red"
    assert d.metadata["approval_required"] is True
