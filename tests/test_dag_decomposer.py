from opencobalt.core.dag_decomposer import DAGDecomposer, DAGSubTask


def test_decompose_dag_returns_dag_subtasks():
    d = DAGDecomposer()
    subtasks = d.decompose_dag("implement the login feature")
    assert all(isinstance(st, DAGSubTask) for st in subtasks)
    assert len(subtasks) >= 1


def test_impl_task_has_empty_depends_on():
    d = DAGDecomposer()
    subtasks = d.decompose_dag("implement OAuth")
    impl_tasks = [st for st in subtasks if st.task_type == "impl"]
    assert impl_tasks
    assert impl_tasks[0].depends_on == []


def test_tests_task_depends_on_impl():
    d = DAGDecomposer()
    subtasks = d.decompose_dag("implement auth with tests")
    impl_ids = {st.id for st in subtasks if st.task_type == "impl"}
    test_tasks = [st for st in subtasks if st.task_type == "tests"]
    assert test_tasks
    assert all(dep in impl_ids for dep in test_tasks[0].depends_on)


def test_docs_task_depends_on_impl():
    d = DAGDecomposer()
    subtasks = d.decompose_dag("implement auth and document it")
    impl_ids = {st.id for st in subtasks if st.task_type == "impl"}
    doc_tasks = [st for st in subtasks if st.task_type == "docs"]
    if doc_tasks:
        assert all(dep in impl_ids for dep in doc_tasks[0].depends_on)


def test_impl_produces_impl_code_and_diff():
    d = DAGDecomposer()
    subtasks = d.decompose_dag("implement auth")
    impl = next(st for st in subtasks if st.task_type == "impl")
    assert "impl_code" in impl.produces
    assert "diff" in impl.produces


def test_tests_consumes_impl_code():
    d = DAGDecomposer()
    subtasks = d.decompose_dag("implement with tests")
    test_task = next((st for st in subtasks if st.task_type == "tests"), None)
    if test_task:
        assert "impl_code" in test_task.consumes


def test_to_waves_impl_before_tests():
    d = DAGDecomposer()
    subtasks = d.decompose_dag("implement auth with tests")
    waves = d.to_waves(subtasks)
    assert len(waves) >= 2
    wave_0_types = {st.task_type for st in waves[0]}
    assert "impl" in wave_0_types
    wave_1_types = {st.task_type for st in waves[1]}
    assert "tests" in wave_1_types


def test_to_waves_covers_all_subtasks():
    d = DAGDecomposer()
    subtasks = d.decompose_dag("implement auth with tests and documentation")
    waves = d.to_waves(subtasks)
    all_ids_in_waves = {st.id for wave in waves for st in wave}
    assert {st.id for st in subtasks} == all_ids_in_waves


def test_to_waves_single_impl_task_is_one_wave():
    d = DAGDecomposer()
    subtasks = d.decompose_dag("implement the feature")
    waves = d.to_waves(subtasks)
    assert len(waves) == 1
    assert subtasks[0].id in {st.id for st in waves[0]}


def test_dag_subtask_has_all_required_fields():
    d = DAGDecomposer()
    subtasks = d.decompose_dag("implement auth")
    st = subtasks[0]
    assert st.id
    assert st.prompt
    assert st.task_type
    assert st.preferred_tool
    assert isinstance(st.depends_on, list)
    assert isinstance(st.produces, list)
    assert isinstance(st.consumes, list)
