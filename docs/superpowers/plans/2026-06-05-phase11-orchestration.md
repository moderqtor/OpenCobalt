# Phase 11: Multi-Agent Orchestration DSL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an orchestration DSL (`/orch`) that decomposes a task into typed subtasks, dispatches each to a specialized agent in parallel, merges outputs, and logs a `MultiRouteDecision` to the ledger.

**Architecture:** A keyword-based `TaskDecomposer` splits any task into typed subtasks (impl, tests, docs, review, analyze, summarize). A `SubagentRegistry` maps each type to the best installed tool (claude-code, codex-cli, gemini-cli, ollama). An `OrchestrationExecutor` fans all subtasks out in parallel via its own `BackgroundRunner(max_workers=6)`, then `ResultSynthesizer` merges outputs with attribution headers.

**Tech Stack:** Python 3.11+, stdlib `sqlite3`, `pydantic`, `rich`, `prompt_toolkit`, existing `BackgroundRunner` + `consult_subprocess` from `council.py`.

---

## File map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `src/opencobalt/core/models.py` | Add `SubTask`, `OrchestrationResult`, `MultiRouteDecision` |
| Create | `src/opencobalt/core/decomposer.py` | `TaskDecomposer` -- keyword split into typed subtasks |
| Create | `src/opencobalt/core/subagent_registry.py` | `SubagentRegistry` -- specialized agent declarations |
| Modify | `src/opencobalt/core/ledger.py` | Add `multi_route_decisions` table + two methods |
| Modify | `src/opencobalt/core/benchmark.py` | Add `subagent_id` + `prompt_style` columns to `BenchmarkRecord` |
| Create | `src/opencobalt/core/orchestrator.py` | `OrchestrationSession`, `OrchestrationExecutor`, `ResultSynthesizer`, DSL parser |
| Modify | `src/opencobalt/shell.py` | Add `/orch` command + multi-route hint in `_route_and_open` |
| Modify | `src/opencobalt/cli.py` | Add `opencobalt orch TASK` command |
| Create | `tests/test_decomposer.py` | Unit tests for `TaskDecomposer` |
| Create | `tests/test_subagent_registry.py` | Unit tests for `SubagentRegistry` |
| Create | `tests/test_orchestrator.py` | Unit tests for executor + synthesizer + DSL parser |
| Create | `tests/test_multi_route_ledger.py` | Ledger round-trip tests for `MultiRouteDecision` |
| Create | `tests/test_benchmark_subagent.py` | Tests for new `subagent_id` / `prompt_style` fields |

---

## Task 1: New models -- SubTask, OrchestrationResult, MultiRouteDecision

**Files:**
- Modify: `src/opencobalt/core/models.py`
- Test: `tests/test_models.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_models.py`:

```python
from opencobalt.core.models import SubTask, OrchestrationResult, MultiRouteDecision


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_models.py::test_subtask_defaults tests/test_models.py::test_orchestration_result_success_flag tests/test_models.py::test_multi_route_decision_fields -v
```

Expected: ImportError (models not defined yet).

- [ ] **Step 3: Add models to `src/opencobalt/core/models.py`**

Append after the `DesignBrief` class:

```python
class SubTask(BaseModel):
    id: str = Field(default_factory=_uid)
    task_type: str
    prompt: str
    preferred_tool: str
    preferred_agent: str | None = None


class OrchestrationResult(BaseModel):
    id: str = Field(default_factory=_uid)
    timestamp: datetime = Field(default_factory=_now)
    task: str
    subtasks: list[SubTask]
    outputs: dict[str, str] = Field(default_factory=dict)
    synthesis: str = ""
    elapsed_s: float = 0.0
    success: bool = False
    errors: list[str] = Field(default_factory=list)


class MultiRouteDecision(BaseModel):
    id: str = Field(default_factory=_uid)
    timestamp: datetime = Field(default_factory=_now)
    task: str
    subtasks: list[SubTask]
    tools_used: list[str] = Field(default_factory=list)
    result_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_models.py::test_subtask_defaults tests/test_models.py::test_orchestration_result_success_flag tests/test_models.py::test_multi_route_decision_fields -v
```

Expected: 3 passed.

- [ ] **Step 5: Run full suite to verify no regressions**

```bash
python3 -m pytest -q
```

Expected: all existing tests pass + 3 new.

- [ ] **Step 6: Commit**

```bash
git add src/opencobalt/core/models.py tests/test_models.py
git commit -m "feat(phase11): add SubTask, OrchestrationResult, MultiRouteDecision models"
```

---

## Task 2: TaskDecomposer

**Files:**
- Create: `src/opencobalt/core/decomposer.py`
- Create: `tests/test_decomposer.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_decomposer.py`:

```python
from opencobalt.core.decomposer import TaskDecomposer
from opencobalt.core.models import SubTask


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_decomposer.py -v
```

Expected: ImportError.

- [ ] **Step 3: Create `src/opencobalt/core/decomposer.py`**

```python
"""Keyword-based task decomposer for multi-agent orchestration.

No LLM required. Maps task descriptions to typed subtasks using the same
keyword scoring approach as the main router.
"""

from __future__ import annotations

from .models import SubTask

_TYPE_KEYWORDS: dict[str, list[str]] = {
    "impl": [
        "implement", "build", "create", "add", "write", "develop", "code",
        "refactor", "fix", "update", "integrate", "connect", "wire",
    ],
    "tests": [
        "test", "tests", "spec", "pytest", "coverage", "assert", "unit",
        "integration", "tdd", "verify tests",
    ],
    "docs": [
        "document", "docs", "docstring", "readme", "changelog", "comment",
        "explain", "describe",
    ],
    "review": [
        "review", "audit security", "security review", "check for", "lint",
        "validate", "inspect",
    ],
    "analyze": [
        "audit", "analyze", "analyse", "scan", "search", "entire", "all files",
        "codebase", "read through", "comprehensive",
    ],
    "summarize": [
        "summarize", "summary", "shorten", "compress", "paraphrase",
        "extract", "brief",
    ],
}

_TYPE_TO_TOOL: dict[str, str] = {
    "impl": "claude-code",
    "tests": "codex-cli",
    "docs": "codex-cli",
    "review": "claude-code",
    "analyze": "gemini-cli",
    "summarize": "ollama",
}


class TaskDecomposer:
    """Decompose a task string into typed SubTasks via keyword scoring."""

    def decompose(self, task: str) -> list[SubTask]:
        task_lower = task.lower()
        matched: list[str] = []

        for task_type, keywords in _TYPE_KEYWORDS.items():
            if any(kw in task_lower for kw in keywords):
                matched.append(task_type)

        if not matched:
            matched = ["impl"]

        subtasks = []
        for task_type in matched:
            tool = _TYPE_TO_TOOL.get(task_type, "claude-code")
            prompt = self._build_prompt(task, task_type)
            subtasks.append(
                SubTask(
                    task_type=task_type,
                    prompt=prompt,
                    preferred_tool=tool,
                )
            )

        return subtasks

    def _build_prompt(self, task: str, task_type: str) -> str:
        prefixes = {
            "impl": "Implement the following",
            "tests": "Write comprehensive tests for the following",
            "docs": "Write clear documentation for the following",
            "review": "Review the following for correctness and quality",
            "analyze": "Analyze the following thoroughly",
            "summarize": "Summarize the following concisely",
        }
        prefix = prefixes.get(task_type, "Handle the following")
        return f"{prefix}: {task}"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_decomposer.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Run full suite**

```bash
python3 -m pytest -q
```

Expected: all previous tests pass + 8 new.

- [ ] **Step 6: Commit**

```bash
git add src/opencobalt/core/decomposer.py tests/test_decomposer.py
git commit -m "feat(phase11): TaskDecomposer -- keyword-based subtask splitting"
```

---

## Task 3: SubagentRegistry

**Files:**
- Create: `src/opencobalt/core/subagent_registry.py`
- Create: `tests/test_subagent_registry.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_subagent_registry.py`:

```python
from opencobalt.core.subagent_registry import SubagentRegistry, SubagentSpec


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_subagent_registry.py -v
```

Expected: ImportError.

- [ ] **Step 3: Create `src/opencobalt/core/subagent_registry.py`**

```python
"""Specialized subagent registry for multi-agent orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SubagentSpec:
    agent_id: str
    specialization: str
    tier: str
    tool: str
    task_types: list[str]
    prompt_template: str = ""


_REGISTRY: list[SubagentSpec] = [
    SubagentSpec(
        agent_id="impl-agent",
        specialization="code implementation",
        tier="executive",
        tool="claude-code",
        task_types=["impl"],
        prompt_template="Implement the following task precisely and completely: {task}",
    ),
    SubagentSpec(
        agent_id="test-gen",
        specialization="test generation",
        tier="manager",
        tool="codex-cli",
        task_types=["tests"],
        prompt_template="Write comprehensive pytest tests for: {task}",
    ),
    SubagentSpec(
        agent_id="doc-writer",
        specialization="documentation",
        tier="manager",
        tool="codex-cli",
        task_types=["docs"],
        prompt_template="Write clear, concise documentation for: {task}",
    ),
    SubagentSpec(
        agent_id="security-reviewer",
        specialization="security audit",
        tier="executive",
        tool="claude-code",
        task_types=["review"],
        prompt_template="Review the following for security and correctness issues: {task}",
    ),
    SubagentSpec(
        agent_id="analyst-agent",
        specialization="long-context analysis, audit, cross-file search",
        tier="executive",
        tool="gemini-cli",
        task_types=["analyze"],
        prompt_template="Analyze the following thoroughly across all relevant files: {task}",
    ),
    SubagentSpec(
        agent_id="summarizer",
        specialization="summarization",
        tier="worker",
        tool="ollama",
        task_types=["summarize"],
        prompt_template="Summarize the following concisely: {task}",
    ),
]


class SubagentRegistry:
    """Lookup specialized subagent specs by task type or agent ID."""

    def list_all(self) -> list[SubagentSpec]:
        return list(_REGISTRY)

    def get_for_task_type(self, task_type: str) -> SubagentSpec | None:
        for spec in _REGISTRY:
            if task_type in spec.task_types:
                return spec
        return None

    def get(self, agent_id: str) -> SubagentSpec | None:
        for spec in _REGISTRY:
            if spec.agent_id == agent_id:
                return spec
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_subagent_registry.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Run full suite**

```bash
python3 -m pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add src/opencobalt/core/subagent_registry.py tests/test_subagent_registry.py
git commit -m "feat(phase11): SubagentRegistry with 6 specialized agents"
```

---

## Task 4: Ledger extension -- MultiRouteDecision persistence

**Files:**
- Modify: `src/opencobalt/core/ledger.py`
- Create: `tests/test_multi_route_ledger.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_multi_route_ledger.py`:

```python
import pytest
from opencobalt.core.ledger import Ledger
from opencobalt.core.models import MultiRouteDecision, SubTask


@pytest.fixture
def ledger(tmp_path):
    return Ledger(db_path=tmp_path / "test.db")


def _make_decision():
    st = SubTask(task_type="impl", prompt="build it", preferred_tool="claude-code")
    return MultiRouteDecision(
        task="implement auth",
        subtasks=[st],
        tools_used=["claude-code"],
        result_id="abc123",
    )


def test_insert_multi_route_decision(ledger):
    d = _make_decision()
    ledger.insert_multi_route_decision(d)


def test_list_multi_route_decisions_returns_inserted(ledger):
    d = _make_decision()
    ledger.insert_multi_route_decision(d)
    results = ledger.list_multi_route_decisions()
    assert len(results) == 1
    assert results[0].task == "implement auth"
    assert results[0].tools_used == ["claude-code"]


def test_list_multi_route_decisions_limit(ledger):
    for i in range(5):
        st = SubTask(task_type="impl", prompt=f"task {i}", preferred_tool="claude-code")
        d = MultiRouteDecision(
            task=f"task {i}",
            subtasks=[st],
            tools_used=["claude-code"],
            result_id=f"r{i}",
        )
        ledger.insert_multi_route_decision(d)
    results = ledger.list_multi_route_decisions(limit=3)
    assert len(results) == 3


def test_insert_idempotent(ledger):
    d = _make_decision()
    ledger.insert_multi_route_decision(d)
    ledger.insert_multi_route_decision(d)
    results = ledger.list_multi_route_decisions()
    assert len(results) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_multi_route_ledger.py -v
```

Expected: AttributeError (method not defined yet).

- [ ] **Step 3: Add schema and methods to `src/opencobalt/core/ledger.py`**

Add the table to `_SCHEMA` (append inside the triple-quoted string before the closing `"""`):

```python
CREATE TABLE IF NOT EXISTS multi_route_decisions (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    task        TEXT NOT NULL,
    subtasks    TEXT NOT NULL DEFAULT '[]',
    tools_used  TEXT NOT NULL DEFAULT '[]',
    result_id   TEXT NOT NULL DEFAULT '',
    metadata    TEXT NOT NULL DEFAULT '{}'
);
```

Add to the imports at the top of `ledger.py` (extend the existing import):

```python
from .models import (
    MemoryRecord,
    MultiRouteDecision,
    RouteDecision,
    SessionEvent,
    SubTask,
    VerificationResult,
)
```

Append two methods to the `Ledger` class (after `list_outcomes`):

```python
# --- Multi-route decisions ---

def insert_multi_route_decision(self, decision: MultiRouteDecision) -> None:
    with self._connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO multi_route_decisions VALUES (?,?,?,?,?,?,?)",
            (
                decision.id,
                decision.timestamp.isoformat(),
                decision.task,
                json.dumps([st.model_dump() for st in decision.subtasks]),
                json.dumps(decision.tools_used),
                decision.result_id,
                json.dumps(decision.metadata),
            ),
        )

def list_multi_route_decisions(self, *, limit: int = 20) -> list[MultiRouteDecision]:
    with self._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM multi_route_decisions ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
    results = []
    for r in rows:
        subtasks = [SubTask(**s) for s in json.loads(r["subtasks"])]
        results.append(
            MultiRouteDecision(
                id=r["id"],
                timestamp=r["timestamp"],
                task=r["task"],
                subtasks=subtasks,
                tools_used=json.loads(r["tools_used"]),
                result_id=r["result_id"],
                metadata=json.loads(r["metadata"]),
            )
        )
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_multi_route_ledger.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Run full suite**

```bash
python3 -m pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add src/opencobalt/core/ledger.py tests/test_multi_route_ledger.py
git commit -m "feat(phase11): add multi_route_decisions table and Ledger methods"
```

---

## Task 5: BenchmarkRecord -- subagent_id and prompt_style columns

**Files:**
- Modify: `src/opencobalt/core/benchmark.py`
- Create: `tests/test_benchmark_subagent.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_benchmark_subagent.py`:

```python
import pytest
from opencobalt.core.benchmark import BenchmarkRecord, BenchmarkStore


@pytest.fixture
def store(tmp_path):
    return BenchmarkStore(db_path=tmp_path / "bench.db")


def test_record_with_subagent_id(store):
    r = BenchmarkRecord(
        agent_id="impl-agent",
        task_id="t1",
        task_type="impl",
        latency_ms=200,
        success=True,
        model_used="claude-code",
        tier="executive",
        score=0.85,
        subagent_id="impl-agent",
        prompt_style="imperative",
    )
    store.record(r)
    rows = store.list_recent(limit=1)
    assert rows[0]["subagent_id"] == "impl-agent"
    assert rows[0]["prompt_style"] == "imperative"


def test_record_without_subagent_fields_defaults_none(store):
    r = BenchmarkRecord(
        agent_id="codex-cli",
        task_id="t2",
        task_type="tests",
        latency_ms=500,
        success=True,
        model_used="codex-cli",
        tier="manager",
        score=0.7,
    )
    store.record(r)
    rows = store.list_recent(limit=1)
    assert rows[0]["subagent_id"] is None
    assert rows[0]["prompt_style"] is None


def test_leaderboard_still_works(store):
    for i in range(3):
        r = BenchmarkRecord(
            agent_id="impl-agent",
            task_id=f"t{i}",
            task_type="impl",
            latency_ms=300,
            success=True,
            model_used="claude-code",
            tier="executive",
            score=0.9,
        )
        store.record(r)
    lb = store.get_leaderboard()
    assert lb[0]["agent_id"] == "impl-agent"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_benchmark_subagent.py -v
```

Expected: TypeError (unexpected keyword arguments).

- [ ] **Step 3: Update `src/opencobalt/core/benchmark.py`**

Add two optional fields to `BenchmarkRecord`:

```python
@dataclass
class BenchmarkRecord:
    agent_id: str
    task_id: str
    task_type: str
    latency_ms: int
    success: bool
    model_used: str
    tier: str
    score: float
    id: str = field(default_factory=_uid)
    timestamp: str = field(default_factory=_now_iso)
    subagent_id: str | None = None
    prompt_style: str | None = None
```

Update `_SCHEMA` to add the two columns:

```python
_SCHEMA = """
CREATE TABLE IF NOT EXISTS benchmark_records (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    task_id     TEXT NOT NULL,
    task_type   TEXT NOT NULL,
    latency_ms  INTEGER NOT NULL,
    success     INTEGER NOT NULL,
    model_used  TEXT NOT NULL,
    tier        TEXT NOT NULL,
    score       REAL NOT NULL,
    subagent_id TEXT,
    prompt_style TEXT
);
"""
```

Update `_init_schema` to run a migration for existing DBs (add after `conn.executescript(_SCHEMA)`):

```python
def _init_schema(self) -> None:
    with self._connect() as conn:
        conn.executescript(_SCHEMA)
        for col, typedef in [("subagent_id", "TEXT"), ("prompt_style", "TEXT")]:
            try:
                conn.execute(
                    f"ALTER TABLE benchmark_records ADD COLUMN {col} {typedef}"
                )
            except Exception:
                pass
```

Update `record()` to include the new fields:

```python
def record(self, result: BenchmarkRecord) -> None:
    with self._connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO benchmark_records "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                result.id,
                result.timestamp,
                result.agent_id,
                result.task_id,
                result.task_type,
                result.latency_ms,
                int(result.success),
                result.model_used,
                result.tier,
                result.score,
                result.subagent_id,
                result.prompt_style,
            ),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_benchmark_subagent.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Run full suite**

```bash
python3 -m pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add src/opencobalt/core/benchmark.py tests/test_benchmark_subagent.py
git commit -m "feat(phase11): add subagent_id and prompt_style to BenchmarkRecord"
```

---

## Task 6: OrchestrationExecutor + ResultSynthesizer

**Files:**
- Create: `src/opencobalt/core/orchestrator.py` (partial -- this task adds executor + synthesizer)
- Create: `tests/test_orchestrator.py` (partial)

- [ ] **Step 1: Write failing tests**

Create `tests/test_orchestrator.py`:

```python
import pytest
from unittest.mock import patch
from opencobalt.core.orchestrator import OrchestrationExecutor, ResultSynthesizer
from opencobalt.core.models import SubTask, OrchestrationResult


def _make_subtask(task_type: str, tool: str) -> SubTask:
    return SubTask(
        task_type=task_type,
        prompt=f"do the {task_type}",
        preferred_tool=tool,
    )


def test_synthesizer_merges_outputs():
    st1 = _make_subtask("impl", "claude-code")
    st2 = _make_subtask("tests", "codex-cli")
    outputs = {st1.id: "impl output", st2.id: "test output"}
    subtasks = [st1, st2]
    s = ResultSynthesizer()
    result = s.synthesize("build auth", subtasks, outputs)
    assert "impl output" in result
    assert "test output" in result
    assert "impl-agent" in result or "impl" in result


def test_synthesizer_empty_outputs():
    s = ResultSynthesizer()
    result = s.synthesize("build auth", [], {})
    assert isinstance(result, str)


def test_executor_runs_subtasks(tmp_path):
    st1 = _make_subtask("impl", "claude-code")
    st2 = _make_subtask("tests", "codex-cli")

    def fake_dispatch(subtask):
        return f"output for {subtask.task_type}"

    executor = OrchestrationExecutor()
    with patch.object(executor, "_dispatch_subtask", side_effect=fake_dispatch):
        result = executor.run("build auth", [st1, st2])

    assert result.success
    assert len(result.outputs) == 2
    assert result.elapsed_s >= 0


def test_executor_handles_missing_tool(tmp_path):
    st = _make_subtask("impl", "nonexistent-tool-xyz")
    executor = OrchestrationExecutor()
    result = executor.run("build auth", [st])
    assert not result.success or result.outputs.get(st.id, "").startswith("[")


def test_executor_partial_failure_still_succeeds(tmp_path):
    st_good = _make_subtask("summarize", "ollama")
    st_bad = _make_subtask("impl", "nonexistent-xyz")

    call_count = {"n": 0}

    def fake_dispatch(subtask):
        call_count["n"] += 1
        if subtask.preferred_tool == "nonexistent-xyz":
            return "[nonexistent-xyz not available]"
        return "summarized output"

    executor = OrchestrationExecutor()
    with patch.object(executor, "_dispatch_subtask", side_effect=fake_dispatch):
        result = executor.run("do stuff", [st_good, st_bad])

    assert result.success
    assert call_count["n"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_orchestrator.py -v
```

Expected: ImportError.

- [ ] **Step 3: Create `src/opencobalt/core/orchestrator.py`** (executor + synthesizer only for now)

```python
"""Multi-agent orchestration: executor, synthesizer, DSL parser, session."""

from __future__ import annotations

import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .models import OrchestrationResult, SubTask
from .subagent_registry import SubagentRegistry

_BINARY_MAP = {
    "claude-code": "claude",
    "codex-cli": "codex",
    "gemini-cli": "gemini",
    "ollama": "ollama",
}


class ResultSynthesizer:
    """Merge per-subtask outputs into a single attributed text block."""

    def synthesize(
        self,
        task: str,
        subtasks: list[SubTask],
        outputs: dict[str, str],
    ) -> str:
        if not subtasks or not outputs:
            return f"No outputs produced for: {task}"

        registry = SubagentRegistry()
        lines = [f"# Orchestration result: {task}\n"]
        for st in subtasks:
            spec = registry.get_for_task_type(st.task_type)
            label = spec.agent_id if spec else st.task_type
            output = outputs.get(st.id, "[no output]")
            lines.append(f"## [{label}] ({st.task_type})\n")
            lines.append(output.strip())
            lines.append("")
        return "\n".join(lines)


class OrchestrationExecutor:
    """Dispatch subtasks in parallel using a dedicated thread pool."""

    def __init__(self, max_workers: int = 6, timeout_s: int = 120) -> None:
        self._max_workers = max_workers
        self._timeout_s = timeout_s

    def run(self, task: str, subtasks: list[SubTask]) -> OrchestrationResult:
        t0 = time.monotonic()
        outputs: dict[str, str] = {}
        errors: list[str] = []

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {
                pool.submit(self._dispatch_subtask, st): st
                for st in subtasks
            }
            for future in as_completed(futures, timeout=self._timeout_s * len(subtasks)):
                st = futures[future]
                try:
                    outputs[st.id] = future.result(timeout=self._timeout_s)
                except Exception as exc:
                    outputs[st.id] = f"[error: {exc}]"
                    errors.append(f"{st.task_type}: {exc}")

        elapsed = round(time.monotonic() - t0, 2)
        real_outputs = {k: v for k, v in outputs.items() if not v.startswith("[error")}
        success = len(real_outputs) > 0

        synthesizer = ResultSynthesizer()
        synthesis = synthesizer.synthesize(task, subtasks, outputs)

        return OrchestrationResult(
            task=task,
            subtasks=subtasks,
            outputs=outputs,
            synthesis=synthesis,
            elapsed_s=elapsed,
            success=success,
            errors=errors,
        )

    def _dispatch_subtask(self, subtask: SubTask) -> str:
        from .council import consult_subprocess

        binary_key = subtask.preferred_tool
        binary = _BINARY_MAP.get(binary_key, binary_key)

        if not shutil.which(binary):
            return f"[{binary_key} not available -- install {binary} or check PATH]"

        return consult_subprocess(subtask.prompt, model=binary_key.split("-")[0])
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_orchestrator.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Run full suite**

```bash
python3 -m pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add src/opencobalt/core/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(phase11): OrchestrationExecutor and ResultSynthesizer"
```

---

## Task 7: DSL parser + OrchestrationSession

**Files:**
- Modify: `src/opencobalt/core/orchestrator.py` (append DSL parser + session)
- Modify: `tests/test_orchestrator.py` (append DSL + session tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_orchestrator.py`:

```python
from opencobalt.core.orchestrator import OrchestrationDSLParser, OrchestrationSession


def test_dsl_parser_auto_mode():
    p = OrchestrationDSLParser()
    task, explicit_agents = p.parse("implement OAuth2 with tests")
    assert task == "implement OAuth2 with tests"
    assert explicit_agents == []


def test_dsl_parser_explicit_agents():
    p = OrchestrationDSLParser()
    task, explicit_agents = p.parse(
        '"implement auth" -> [claude:impl, codex:tests] -> merge'
    )
    assert task == "implement auth"
    assert "claude" in explicit_agents
    assert "codex" in explicit_agents


def test_dsl_parser_quoted_task_no_stages():
    p = OrchestrationDSLParser()
    task, explicit_agents = p.parse('"just this task"')
    assert task == "just this task"
    assert explicit_agents == []


def test_session_run_auto(tmp_path):
    from unittest.mock import patch
    from opencobalt.core.orchestrator import OrchestrationSession

    session = OrchestrationSession()
    with patch.object(
        session._executor, "_dispatch_subtask", return_value="fake output"
    ):
        result = session.run("implement OAuth2 with tests")

    assert result.success
    assert result.synthesis


def test_session_run_explicit(tmp_path):
    from unittest.mock import patch
    from opencobalt.core.orchestrator import OrchestrationSession

    session = OrchestrationSession()
    with patch.object(
        session._executor, "_dispatch_subtask", return_value="fake output"
    ):
        result = session.run('"implement auth" -> [claude:impl, codex:tests] -> merge')

    assert result.task == "implement auth"
    assert result.success
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
python3 -m pytest tests/test_orchestrator.py::test_dsl_parser_auto_mode tests/test_orchestrator.py::test_session_run_auto -v
```

Expected: ImportError.

- [ ] **Step 3: Append DSL parser and session to `src/opencobalt/core/orchestrator.py`**

First add `import re` to the top of the file (after the existing imports, before the `_BINARY_MAP` line):

```python
import re
```

Then append the following classes at the bottom of the file:

```python


class OrchestrationDSLParser:
    """Parse /orch DSL expressions into (task, explicit_agents) pairs.

    Two forms:
      Auto:     just a task string -> ("task", [])
      Explicit: "task" -> [claude:impl, codex:tests] -> merge -> /verify
                -> ("task", ["claude", "codex"])
    """

    def parse(self, expr: str) -> tuple[str, list[str]]:
        expr = expr.strip()

        quoted = re.match(r'^["\'](.+?)["\'](.*)$', expr)
        if quoted:
            task = quoted.group(1).strip()
            rest = quoted.group(2).strip()
        else:
            arrow_pos = expr.find("->")
            if arrow_pos == -1:
                return expr, []
            task = expr[:arrow_pos].strip().strip("\"'")
            rest = expr[arrow_pos:].strip()

        if not rest:
            return task, []

        bracket_match = re.search(r"\[([^\]]+)\]", rest)
        if not bracket_match:
            return task, []

        agents_raw = bracket_match.group(1)
        agents = [
            part.split(":")[0].strip()
            for part in agents_raw.split(",")
            if part.strip()
        ]
        return task, agents


class OrchestrationSession:
    """Top-level entry point for the /orch shell command."""

    def __init__(self) -> None:
        self._parser = OrchestrationDSLParser()
        self._decomposer_cls = None
        self._executor = OrchestrationExecutor()

    def run(self, expr: str) -> OrchestrationResult:
        from .decomposer import TaskDecomposer

        task, explicit_agents = self._parser.parse(expr)

        if explicit_agents:
            subtasks = self._build_explicit_subtasks(task, explicit_agents)
        else:
            decomposer = TaskDecomposer()
            subtasks = decomposer.decompose(task)

        return self._executor.run(task, subtasks)

    def _build_explicit_subtasks(
        self, task: str, agents: list[str]
    ) -> list[SubTask]:
        _AGENT_TO_TOOL = {
            "claude": "claude-code",
            "codex": "codex-cli",
            "gemini": "gemini-cli",
            "ollama": "ollama",
        }
        _AGENT_TO_TYPE = {
            "claude": "impl",
            "codex": "tests",
            "gemini": "analyze",
            "ollama": "summarize",
        }
        subtasks = []
        for agent in agents:
            tool = _AGENT_TO_TOOL.get(agent, agent)
            task_type = _AGENT_TO_TYPE.get(agent, "impl")
            subtasks.append(
                SubTask(
                    task_type=task_type,
                    prompt=f"{task}",
                    preferred_tool=tool,
                    preferred_agent=agent,
                )
            )
        return subtasks
```

- [ ] **Step 4: Run all orchestrator tests**

```bash
python3 -m pytest tests/test_orchestrator.py -v
```

Expected: all 10 passed.

- [ ] **Step 5: Run full suite**

```bash
python3 -m pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add src/opencobalt/core/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(phase11): OrchestrationDSLParser and OrchestrationSession"
```

---

## Task 8: Shell integration -- /orch command + multi-route hint

**Files:**
- Modify: `src/opencobalt/shell.py`
- Modify: `tests/test_shell.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_shell.py`:

```python
def test_orch_in_slash_commands(shell):
    assert "orch" in shell.list_slash_commands()


def test_dispatch_orch_calls_run_orch(shell, monkeypatch):
    called_with = {}

    def fake_run_orch(expr):
        called_with["expr"] = expr

    monkeypatch.setattr(shell, "_run_orch", fake_run_orch)
    shell.dispatch("/orch implement auth with tests")
    assert called_with.get("expr") == "implement auth with tests"
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
python3 -m pytest tests/test_shell.py::test_orch_in_slash_commands tests/test_shell.py::test_dispatch_orch_calls_run_orch -v
```

Expected: AssertionError (orch not yet registered).

- [ ] **Step 3: Add `/orch` to `src/opencobalt/shell.py`**

In `_CLI_COMMANDS`, add `"orch"` to the list (after `"council"`):

```python
_CLI_COMMANDS = [
    ...
    "council",
    "orch",
    ...
]
```

In the `WordCompleter` list in `__init__`, the `_CLI_COMMANDS` list is already used so no change needed there.

In `_run_command`, add a dispatch branch before the generic `argv` call:

```python
if cmd == "orch":
    self._run_orch(" ".join(args))
    return
```

Add `_run_orch` method to `CobaltShell`:

```python
def _run_orch(self, expr: str) -> None:
    from .core.orchestrator import OrchestrationSession

    if not expr.strip():
        console.print(
            f"  [{_AMBER}]Usage:[/{_AMBER}]  /orch \"task\""
            " or /orch \"task\" -> [claude:impl, codex:tests] -> merge"
        )
        return

    console.print(f"\n  [{_COBALT}]orchestrating[/{_COBALT}]  [dim]{expr[:60]}[/dim]\n")
    session = OrchestrationSession()
    result = session.run(expr)

    for st in result.subtasks:
        status = "[dim]ok[/dim]" if st.id in result.outputs else "[dim]skipped[/dim]"
        console.print(f"  {status}  [dim]{st.task_type} → {st.preferred_tool}[/dim]")

    console.print()
    console.print(result.synthesis)
    console.print(
        f"\n  [dim]elapsed {result.elapsed_s}s · "
        f"{'success' if result.success else 'partial'}[/dim]"
    )

    try:
        from .core.ledger import Ledger
        from .core.models import MultiRouteDecision
        decision = MultiRouteDecision(
            task=result.task,
            subtasks=result.subtasks,
            tools_used=[s.preferred_tool for s in result.subtasks],
            result_id=result.id,
        )
        Ledger(self._db_path).insert_multi_route_decision(decision)
    except Exception:
        pass
```

Add the multi-route hint in `_route_and_open` (after the `decision` assignment):

```python
def _route_and_open(self, task: str) -> None:
    task = self._refine_prompt(task)
    decision = self._learning_router.route(task)

    # Multi-route hint: suggest /orch if task spans multiple tiers
    try:
        from .core.router import _TOOL_PROFILES
        tier_hits: set[str] = set()
        task_lower = task.lower()
        for profile in _TOOL_PROFILES.values():
            if any(kw in task_lower for kw in profile["keywords"]):
                tier_hits.add(profile["tier"])
        if len(tier_hits) >= 2:
            console.print(f"  [dim][multi] try /orch for parallel dispatch[/dim]")
    except Exception:
        pass

    # ... rest of existing method unchanged
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_shell.py -v
```

Expected: all shell tests pass including the two new ones.

- [ ] **Step 5: Run full suite**

```bash
python3 -m pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add src/opencobalt/shell.py tests/test_shell.py
git commit -m "feat(phase11): /orch shell command and multi-route hint"
```

---

## Task 9: CLI command -- opencobalt orch

**Files:**
- Modify: `src/opencobalt/cli.py`
- Modify: `tests/test_cli.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cli.py`:

```python
from typer.testing import CliRunner
from opencobalt.cli import app
from unittest.mock import patch, MagicMock


def test_orch_command_help():
    runner = CliRunner()
    result = runner.invoke(app, ["orch", "--help"])
    assert result.exit_code == 0
    assert "orch" in result.output.lower() or "task" in result.output.lower()


def test_orch_command_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCOBALT_DB", str(tmp_path / "test.db"))
    runner = CliRunner()

    fake_result = MagicMock()
    fake_result.success = True
    fake_result.task = "build auth"
    fake_result.subtasks = []
    fake_result.outputs = {}
    fake_result.synthesis = "merged output"
    fake_result.elapsed_s = 0.1
    fake_result.errors = []

    with patch("opencobalt.cli.OrchestrationSession") as mock_cls:
        mock_cls.return_value.run.return_value = fake_result
        result = runner.invoke(app, ["orch", "build auth"])

    assert result.exit_code == 0
```

- [ ] **Step 2: Run failing tests**

```bash
python3 -m pytest tests/test_cli.py::test_orch_command_help tests/test_cli.py::test_orch_command_runs -v
```

Expected: error (command not registered).

- [ ] **Step 3: Add `orch` command to `src/opencobalt/cli.py`**

Add to imports at top of `cli.py`:

```python
from .core.orchestrator import OrchestrationSession
```

Add the command after the existing `route` command:

```python
@app.command()
def orch(
    task: str = typer.Argument(..., help="Task to orchestrate across multiple agents"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show per-subtask output"),
) -> None:
    """Dispatch a task to multiple specialized agents in parallel."""
    console = Console()
    session = OrchestrationSession()
    console.print(f"\n  [bold]orchestrating[/bold]  [dim]{task[:60]}[/dim]\n")
    result = session.run(task)

    for st in result.subtasks:
        status = "ok" if st.id in result.outputs else "skipped"
        console.print(f"  [dim]{status}  {st.task_type} -> {st.preferred_tool}[/dim]")

    console.print()
    if verbose:
        console.print(result.synthesis)
    else:
        lines = result.synthesis.splitlines()
        for line in lines[:20]:
            console.print(f"  {line}")
        if len(lines) > 20:
            console.print(f"  [dim]... {len(lines) - 20} more lines (use --verbose)[/dim]")

    status_str = "success" if result.success else "partial"
    console.print(f"\n  [dim]{status_str} · {result.elapsed_s}s[/dim]")

    if result.errors:
        for err in result.errors:
            console.print(f"  [dim]error: {err}[/dim]")
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_cli.py::test_orch_command_help tests/test_cli.py::test_orch_command_runs -v
```

Expected: 2 passed.

- [ ] **Step 5: Run full suite**

```bash
python3 -m pytest -q
```

- [ ] **Step 6: public-check**

```bash
opencobalt public-check
```

Expected: no secrets found.

- [ ] **Step 7: Commit**

```bash
git add src/opencobalt/cli.py tests/test_cli.py
git commit -m "feat(phase11): opencobalt orch CLI command"
```

---

## Task 10: Final verification and ROADMAP update

**Files:**
- Modify: `docs/ROADMAP.md`

- [ ] **Step 1: Full test suite green**

```bash
python3 -m pytest -q
```

Expected: all tests pass (previous baseline + all new tests).

- [ ] **Step 2: Smoke test the CLI command**

```bash
opencobalt orch "summarize the project" --verbose
```

Expected: output shows subtasks dispatched, synthesis printed (tools will report unavailable if not installed -- that is expected behaviour).

- [ ] **Step 3: public-check**

```bash
opencobalt public-check
```

Expected: clean.

- [ ] **Step 4: Update ROADMAP -- move Phase 11 to Completed**

In `docs/ROADMAP.md`, move the Phase 11 block from "In Progress / Next" to "Completed" and add a summary line:

```markdown
### Phase 11: Multi-Agent Orchestration

- Orchestration DSL: `/orch "task"` and `/orch "task" -> [claude:impl, codex:tests] -> merge`
- `TaskDecomposer`: keyword-based split into typed subtasks (impl, tests, docs, review, analyze, summarize)
- `SubagentRegistry`: 6 specialized agents (impl-agent, test-gen, doc-writer, security-reviewer, analyst-agent, summarizer)
- `OrchestrationExecutor`: parallel fan-out via dedicated `BackgroundRunner(max_workers=6)`
- `MultiRouteDecision` model and ledger table for full fan-out audit trail
- `BenchmarkRecord` extended with `subagent_id` and `prompt_style` columns
- `opencobalt orch TASK` CLI command
- Multi-route hint in `_route_and_open` when task spans multiple tiers
```

- [ ] **Step 5: Commit**

```bash
git add docs/ROADMAP.md
git commit -m "docs: mark Phase 11 complete in ROADMAP"
```
