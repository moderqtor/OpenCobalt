from opencobalt.core.decomposer import TaskDecomposer


def test_impl_task_detected():
    d = TaskDecomposer()
    subtasks = d.decompose("implement the OAuth2 login flow")
    types = [s.task_type for s in subtasks]
    assert "impl" in types


def test_test_task_detected():
    d = TaskDecomposer()
    subtasks = d.decompose("write tests for the auth module")
    types = [s.task_type for s in subtasks]
    assert "tests" in types


def test_docs_task_detected():
    d = TaskDecomposer()
    subtasks = d.decompose("document the API endpoints")
    types = [s.task_type for s in subtasks]
    assert "docs" in types


def test_analyze_task_detected():
    d = TaskDecomposer()
    subtasks = d.decompose("audit the entire codebase for security issues")
    types = [s.task_type for s in subtasks]
    assert "analyze" in types


def test_complex_task_produces_multiple_subtasks():
    d = TaskDecomposer()
    subtasks = d.decompose("implement auth with tests and documentation")
    assert len(subtasks) >= 2


def test_subtask_prompt_contains_original_task():
    d = TaskDecomposer()
    subtasks = d.decompose("add rate limiting")
    for st in subtasks:
        assert "rate limiting" in st.prompt


def test_subtask_has_preferred_tool():
    d = TaskDecomposer()
    subtasks = d.decompose("implement the login route")
    for st in subtasks:
        assert st.preferred_tool


def test_single_clear_task_returns_one_subtask():
    d = TaskDecomposer()
    subtasks = d.decompose("summarize this file")
    assert len(subtasks) == 1
    assert subtasks[0].task_type == "summarize"
