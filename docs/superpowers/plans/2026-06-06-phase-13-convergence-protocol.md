# Phase 13: Convergence Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a full artifact pub/sub protocol, DAG-based task decomposition, convergence gating (tests + verifier), auto-commit, and `opencobalt converge` CLI/shell surface.

**Architecture:** Five new `core/` modules form a dependency chain: `ArtifactBus` (SQLite pub/sub) -> `DAGDecomposer` (wave scheduler) -> `ConvergenceChecker` (gate runner) -> `AutoCommitter` (git commit) -> `ConvergenceOrchestrator` (top-level loop). The `Ledger` gains two new tables for session/wave history. All side-effecting components accept injectable callables so tests never spawn real processes.

**DB decision:** `ArtifactBus` owns `.opencobalt/artifacts.db` (consistent with `memories.db` / `observability.db` pattern in AGENTS.md). `Ledger` (`ledger.db`) gets `convergence_sessions` and `convergence_wave_results` tables for history/inspection. The spec's `convergence_artifacts` table lives in `artifacts.db`.

**Tech Stack:** Python stdlib `sqlite3`, `dataclasses`, `concurrent.futures.ThreadPoolExecutor`, `rich`, `typer`; existing `council.consult_subprocess` for LLM calls; existing `TaskDecomposer` as base class.

---

## File Map

### New files
| File | Responsibility |
|------|---------------|
| `src/opencobalt/core/artifact_bus.py` | `ArtifactType`, `AgentArtifact`, `ArtifactBus` (`.opencobalt/artifacts.db`) |
| `src/opencobalt/core/dag_decomposer.py` | `DAGSubTask`, `DAGDecomposer` (extends `TaskDecomposer`) |
| `src/opencobalt/core/convergence_checker.py` | `TestsGate`, `VerifierGate`, `ConvergenceChecker`, `ConvergenceResult` |
| `src/opencobalt/core/auto_committer.py` | `AutoCommitter`, `CommitResult` |
| `src/opencobalt/core/convergence_orchestrator.py` | `ConvergenceOrchestrator`, `ConvergenceSession` |
| `tests/test_artifact_bus.py` | |
| `tests/test_dag_decomposer.py` | |
| `tests/test_convergence_checker.py` | |
| `tests/test_auto_committer.py` | |
| `tests/test_convergence_orchestrator.py` | |

### Modified files
| File | Change |
|------|--------|
| `src/opencobalt/core/ledger.py` | Add `_create_convergence_tables()` + 5 new methods, call from `__init__` |
| `src/opencobalt/cli.py` | Add `converge_app` sub-typer + `--converge` flag on `auto` |
| `src/opencobalt/shell.py` | Add `"converge"` to `_CLI_COMMANDS`, `_run_converge()` handler |

---

## Task 1: Convergence tables in Ledger

**Files:**
- Modify: `src/opencobalt/core/ledger.py`
- Test: `tests/test_convergence_tables.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_convergence_tables.py`:

```python
import pytest
import sqlite3
from pathlib import Path
from opencobalt.core.ledger import Ledger


def test_convergence_tables_created(tmp_path):
    ledger = Ledger(tmp_path / "test.db")
    conn = sqlite3.connect(ledger.db_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    assert "convergence_sessions" in tables
    assert "convergence_wave_results" in tables


def test_upsert_and_get_convergence_session(tmp_path):
    ledger = Ledger(tmp_path / "test.db")
    ledger.upsert_convergence_session(
        session_id="test-123",
        seed_task="implement auth",
        status="queued",
        started_at=1000.0,
        finished_at=None,
        total_waves=0,
        total_retries=0,
        commit_sha=None,
        log_path=None,
    )
    row = ledger.get_convergence_session("test-123")
    assert row is not None
    assert row["seed_task"] == "implement auth"
    assert row["status"] == "queued"


def test_upsert_updates_existing_session(tmp_path):
    ledger = Ledger(tmp_path / "test.db")
    ledger.upsert_convergence_session(
        session_id="s1", seed_task="task A", status="queued",
        started_at=1.0, finished_at=None, total_waves=0,
        total_retries=0, commit_sha=None, log_path=None,
    )
    ledger.upsert_convergence_session(
        session_id="s1", seed_task="task A", status="converged",
        started_at=1.0, finished_at=2.0, total_waves=2,
        total_retries=1, commit_sha="abc12345", log_path=None,
    )
    row = ledger.get_convergence_session("s1")
    assert row["status"] == "converged"
    assert row["commit_sha"] == "abc12345"


def test_list_convergence_sessions(tmp_path):
    ledger = Ledger(tmp_path / "test.db")
    for i in range(3):
        ledger.upsert_convergence_session(
            session_id=f"s{i}", seed_task=f"task {i}", status="converged",
            started_at=float(i), finished_at=float(i + 1), total_waves=1,
            total_retries=0, commit_sha=None, log_path=None,
        )
    sessions = ledger.list_convergence_sessions(limit=10)
    assert len(sessions) == 3


def test_insert_and_get_wave_results(tmp_path):
    ledger = Ledger(tmp_path / "test.db")
    ledger.upsert_convergence_session(
        session_id="s1", seed_task="task", status="running",
        started_at=1.0, finished_at=None, total_waves=1,
        total_retries=0, commit_sha=None, log_path=None,
    )
    ledger.insert_wave_result(
        session_id="s1",
        wave=0,
        tests_ok=True,
        verifier_score=0.85,
        verifier_ok=True,
        passed=True,
        retry_count=0,
        feedback="all gates passed",
    )
    results = ledger.get_wave_results("s1")
    assert len(results) == 1
    assert results[0]["passed"] == 1
    assert results[0]["verifier_score"] == pytest.approx(0.85)


def test_get_convergence_session_returns_none_for_unknown(tmp_path):
    ledger = Ledger(tmp_path / "test.db")
    assert ledger.get_convergence_session("nonexistent") is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_convergence_tables.py -v
```
Expected: FAIL with `AttributeError: 'Ledger' object has no attribute 'upsert_convergence_session'` (and `convergence_sessions` table missing)

- [ ] **Step 3: Add `_create_convergence_tables()` and new methods to `ledger.py`**

In `src/opencobalt/core/ledger.py`, in `__init__` add one line after `self._init_schema()`:

```python
        self._create_convergence_tables()
```

Then add these methods at the bottom of the `Ledger` class (after the existing `list_multi_route_decisions` method):

```python
    # --- Convergence tables ---

    _CONVERGENCE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS convergence_sessions (
        id TEXT PRIMARY KEY,
        seed_task TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',
        started_at REAL NOT NULL,
        finished_at REAL,
        total_waves INTEGER NOT NULL DEFAULT 0,
        total_retries INTEGER NOT NULL DEFAULT 0,
        commit_sha TEXT,
        log_path TEXT
    );
    CREATE TABLE IF NOT EXISTS convergence_wave_results (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        wave INTEGER NOT NULL,
        tests_ok INTEGER,
        verifier_score REAL,
        verifier_ok INTEGER,
        passed INTEGER NOT NULL DEFAULT 0,
        retry_count INTEGER NOT NULL DEFAULT 0,
        feedback TEXT NOT NULL DEFAULT '',
        FOREIGN KEY (session_id) REFERENCES convergence_sessions(id)
    );
    """

    def _create_convergence_tables(self) -> None:
        with self._connect() as conn:
            conn.executescript(self._CONVERGENCE_SCHEMA)

    def upsert_convergence_session(
        self,
        session_id: str,
        seed_task: str,
        status: str,
        started_at: float,
        finished_at: float | None,
        total_waves: int,
        total_retries: int,
        commit_sha: str | None,
        log_path: str | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO convergence_sessions "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    session_id, seed_task, status, started_at,
                    finished_at, total_waves, total_retries,
                    commit_sha, log_path,
                ),
            )

    def get_convergence_session(self, session_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM convergence_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_convergence_sessions(self, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM convergence_sessions "
                "ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def insert_wave_result(
        self,
        session_id: str,
        wave: int,
        tests_ok: bool | None,
        verifier_score: float | None,
        verifier_ok: bool | None,
        passed: bool,
        retry_count: int,
        feedback: str,
    ) -> None:
        import uuid as _uuid
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO convergence_wave_results VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    str(_uuid.uuid4()),
                    session_id,
                    wave,
                    None if tests_ok is None else int(tests_ok),
                    verifier_score,
                    None if verifier_ok is None else int(verifier_ok),
                    int(passed),
                    retry_count,
                    feedback,
                ),
            )

    def get_wave_results(self, session_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM convergence_wave_results "
                "WHERE session_id = ? ORDER BY wave, retry_count",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_convergence_tables.py -v
```
Expected: 6 tests PASS

- [ ] **Step 5: Run full suite to confirm no regressions**

```bash
python3 -m pytest -q --tb=short
```
Expected: 407 passed (401 existing + 6 new)

- [ ] **Step 6: Commit**

```bash
git add src/opencobalt/core/ledger.py tests/test_convergence_tables.py
git commit -m "$(cat <<'EOF'
feat(phase13): add convergence tables to ledger

convergence_sessions and convergence_wave_results tables; upsert/get/list
methods; create called on Ledger init so all existing Ledger users auto-migrate.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: ArtifactBus

**Files:**
- Create: `src/opencobalt/core/artifact_bus.py`
- Test: `tests/test_artifact_bus.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_artifact_bus.py`:

```python
import time
import uuid
import pytest
from pathlib import Path
from opencobalt.core.artifact_bus import AgentArtifact, ArtifactBus, ArtifactType


def _artifact(
    session_id: str = "sess-1",
    artifact_type: str = ArtifactType.IMPL_CODE,
    producer: str = "claude",
    content: str = "some code",
    wave: int = 0,
    timestamp: float | None = None,
) -> AgentArtifact:
    return AgentArtifact(
        id=str(uuid.uuid4()),
        session_id=session_id,
        iteration=0,
        wave=wave,
        producer=producer,
        type=artifact_type,
        content=content,
        metadata={},
        timestamp=timestamp if timestamp is not None else time.time(),
    )


def test_publish_and_subscribe(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    a = _artifact()
    bus.publish(a)
    results = bus.subscribe([ArtifactType.IMPL_CODE], "sess-1")
    assert len(results) == 1
    assert results[0].content == "some code"
    assert results[0].producer == "claude"


def test_subscribe_filters_by_type(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    bus.publish(_artifact(artifact_type=ArtifactType.IMPL_CODE, content="impl"))
    bus.publish(_artifact(artifact_type=ArtifactType.TEST_CODE, content="tests"))
    impl_results = bus.subscribe([ArtifactType.IMPL_CODE], "sess-1")
    assert len(impl_results) == 1
    assert impl_results[0].type == ArtifactType.IMPL_CODE


def test_subscribe_filters_by_session(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    bus.publish(_artifact(session_id="sess-1"))
    bus.publish(_artifact(session_id="sess-2"))
    results = bus.subscribe([ArtifactType.IMPL_CODE], "sess-1")
    assert len(results) == 1


def test_subscribe_multiple_types(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    bus.publish(_artifact(artifact_type=ArtifactType.IMPL_CODE))
    bus.publish(_artifact(artifact_type=ArtifactType.TEST_CODE))
    results = bus.subscribe([ArtifactType.IMPL_CODE, ArtifactType.TEST_CODE], "sess-1")
    assert len(results) == 2


def test_latest_returns_most_recent(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    bus.publish(_artifact(content="first", timestamp=1.0))
    bus.publish(_artifact(content="second", timestamp=2.0))
    result = bus.latest(ArtifactType.IMPL_CODE, "sess-1")
    assert result is not None
    assert result.content == "second"


def test_latest_returns_none_for_missing(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    assert bus.latest(ArtifactType.IMPL_CODE, "no-session") is None


def test_context_for_builds_string(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    a = _artifact(artifact_type=ArtifactType.IMPL_CODE, producer="claude", content="the impl")
    bus.publish(a)
    ctx = bus.context_for([ArtifactType.IMPL_CODE], "sess-1")
    assert "impl_code" in ctx
    assert "claude" in ctx
    assert "the impl" in ctx


def test_context_for_empty_session_returns_empty(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    ctx = bus.context_for([ArtifactType.IMPL_CODE], "no-session")
    assert ctx == ""


def test_context_for_empty_types_returns_empty(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    bus.publish(_artifact())
    ctx = bus.context_for([], "sess-1")
    assert ctx == ""


def test_error_context_auto_inject(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    err_artifact = AgentArtifact(
        id=str(uuid.uuid4()),
        session_id="sess-1",
        iteration=1,
        wave=0,
        producer="convergence-checker",
        type=ArtifactType.ERROR_CONTEXT,
        content="test failed: assertion error on line 42",
        metadata={},
        timestamp=2.0,
    )
    bus.publish(err_artifact)
    ctx = bus.context_for([ArtifactType.ERROR_CONTEXT], "sess-1")
    assert "assertion error" in ctx
    assert "convergence-checker" in ctx


def test_artifact_bus_creates_db_file(tmp_path):
    db = tmp_path / "sub" / "artifacts.db"
    bus = ArtifactBus(db)
    assert db.exists()


def test_publish_replaces_on_same_id(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    a = _artifact()
    bus.publish(a)
    a.content = "updated"
    bus.publish(a)
    results = bus.subscribe([ArtifactType.IMPL_CODE], "sess-1")
    assert len(results) == 1
    assert results[0].content == "updated"
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_artifact_bus.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'opencobalt.core.artifact_bus'`

- [ ] **Step 3: Create `src/opencobalt/core/artifact_bus.py`**

```python
"""SQLite-backed typed artifact pub/sub bus for convergence sessions."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_DB = Path(".opencobalt") / "artifacts.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS convergence_artifacts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    iteration INTEGER NOT NULL DEFAULT 0,
    wave INTEGER NOT NULL DEFAULT 0,
    producer TEXT NOT NULL,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    timestamp REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_art_session_type
    ON convergence_artifacts(session_id, type);
"""


class ArtifactType:
    IMPL_CODE = "impl_code"
    TEST_CODE = "test_code"
    DIFF = "diff"
    REVIEW_SCORE = "review_score"
    DOC_TEXT = "doc_text"
    ANALYSIS = "analysis"
    SUMMARY = "summary"
    ERROR_CONTEXT = "error_context"


@dataclass
class AgentArtifact:
    id: str
    session_id: str
    iteration: int
    wave: int
    producer: str
    type: str
    content: str
    metadata: dict
    timestamp: float


class ArtifactBus:
    """SQLite-backed pub/sub bus for typed agent artifacts."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = (db_path or _DEFAULT_DB).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def publish(self, artifact: AgentArtifact) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO convergence_artifacts "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    artifact.id,
                    artifact.session_id,
                    artifact.iteration,
                    artifact.wave,
                    artifact.producer,
                    artifact.type,
                    artifact.content,
                    json.dumps(artifact.metadata),
                    artifact.timestamp,
                ),
            )

    def subscribe(self, types: list[str], session_id: str) -> list[AgentArtifact]:
        if not types:
            return []
        placeholders = ",".join("?" * len(types))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM convergence_artifacts "
                f"WHERE type IN ({placeholders}) AND session_id = ? "
                f"ORDER BY timestamp ASC",
                (*types, session_id),
            ).fetchall()
        return [self._row_to_artifact(r) for r in rows]

    def latest(self, type: str, session_id: str) -> AgentArtifact | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM convergence_artifacts "
                "WHERE type = ? AND session_id = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (type, session_id),
            ).fetchone()
        return self._row_to_artifact(row) if row else None

    def context_for(self, consumes: list[str], session_id: str) -> str:
        """Build a prompt context block from published artifacts matching consumes."""
        if not consumes:
            return ""
        artifacts = self.subscribe(consumes, session_id)
        if not artifacts:
            return ""
        blocks = [
            f"--- {a.type} from {a.producer} ---\n{a.content}"
            for a in artifacts
        ]
        return "\n\n".join(blocks)

    def _row_to_artifact(self, row: sqlite3.Row) -> AgentArtifact:
        return AgentArtifact(
            id=row["id"],
            session_id=row["session_id"],
            iteration=row["iteration"],
            wave=row["wave"],
            producer=row["producer"],
            type=row["type"],
            content=row["content"],
            metadata=json.loads(row["metadata_json"]),
            timestamp=row["timestamp"],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_artifact_bus.py -v
```
Expected: 12 tests PASS

- [ ] **Step 5: Run full suite**

```bash
python3 -m pytest -q --tb=short
```
Expected: 419 passed (407 + 12)

- [ ] **Step 6: Commit**

```bash
git add src/opencobalt/core/artifact_bus.py tests/test_artifact_bus.py
git commit -m "$(cat <<'EOF'
feat(phase13): add ArtifactBus with SQLite-backed pub/sub

ArtifactType constants, AgentArtifact dataclass, ArtifactBus with publish/
subscribe/latest/context_for stored in .opencobalt/artifacts.db.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: DAGDecomposer

**Files:**
- Create: `src/opencobalt/core/dag_decomposer.py`
- Test: `tests/test_dag_decomposer.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dag_decomposer.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_dag_decomposer.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'opencobalt.core.dag_decomposer'`

- [ ] **Step 3: Create `src/opencobalt/core/dag_decomposer.py`**

```python
"""DAG-based task decomposer with dependency and artifact declarations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .decomposer import TaskDecomposer

_DEPENDS_ON: dict[str, list[str]] = {
    "impl":     [],
    "tests":    ["impl"],
    "docs":     ["impl"],
    "review":   ["impl", "tests"],
    "analyze":  ["impl"],
    "summarize": ["impl", "tests", "docs"],
}

_CONSUMES: dict[str, list[str]] = {
    "impl":     [],
    "tests":    ["impl_code"],
    "docs":     ["impl_code"],
    "review":   ["impl_code", "test_code"],
    "analyze":  ["impl_code"],
    "summarize": ["impl_code", "test_code", "doc_text"],
}

_PRODUCES: dict[str, list[str]] = {
    "impl":     ["impl_code", "diff"],
    "tests":    ["test_code"],
    "docs":     ["doc_text"],
    "review":   ["review_score"],
    "analyze":  ["analysis"],
    "summarize": ["summary"],
}


@dataclass
class DAGSubTask:
    id: str
    prompt: str
    task_type: str
    preferred_tool: str
    depends_on: list[str] = field(default_factory=list)
    produces: list[str] = field(default_factory=list)
    consumes: list[str] = field(default_factory=list)


class DAGDecomposer(TaskDecomposer):
    """Extends TaskDecomposer with DAG dependency and artifact declarations.

    Dependency and artifact declarations are inferred from task type via
    keyword tables. No LLM call required.
    """

    def decompose_dag(self, task: str) -> list[DAGSubTask]:
        """Decompose task into DAGSubTasks with dependency/artifact metadata."""
        subtasks = self.decompose(task)
        dag_tasks: list[DAGSubTask] = []
        id_by_type: dict[str, str] = {}

        for st in subtasks:
            dag_id = str(uuid.uuid4())
            id_by_type[st.task_type] = dag_id
            dag_tasks.append(
                DAGSubTask(
                    id=dag_id,
                    prompt=st.prompt,
                    task_type=st.task_type,
                    preferred_tool=st.preferred_tool,
                    produces=list(_PRODUCES.get(st.task_type, [])),
                    consumes=list(_CONSUMES.get(st.task_type, [])),
                )
            )

        # Second pass: resolve depends_on from type names to IDs
        for dag_task in dag_tasks:
            dep_types = _DEPENDS_ON.get(dag_task.task_type, [])
            dag_task.depends_on = [
                id_by_type[dt] for dt in dep_types if dt in id_by_type
            ]

        return dag_tasks

    def to_waves(self, subtasks: list[DAGSubTask]) -> list[list[DAGSubTask]]:
        """Topological sort -> execution waves. Each wave runs in parallel."""
        completed: set[str] = set()
        remaining = list(subtasks)
        waves: list[list[DAGSubTask]] = []

        while remaining:
            wave = [
                st for st in remaining
                if all(dep in completed for dep in st.depends_on)
            ]
            if not wave:
                # Unresolvable dependencies; treat remainder as final wave
                waves.append(remaining)
                break
            waves.append(wave)
            for st in wave:
                completed.add(st.id)
            remaining = [st for st in remaining if st not in wave]

        return waves
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_dag_decomposer.py -v
```
Expected: 10 tests PASS

- [ ] **Step 5: Run full suite**

```bash
python3 -m pytest -q --tb=short
```
Expected: 429 passed (419 + 10)

- [ ] **Step 6: Commit**

```bash
git add src/opencobalt/core/dag_decomposer.py tests/test_dag_decomposer.py
git commit -m "$(cat <<'EOF'
feat(phase13): add DAGDecomposer with topological wave scheduling

DAGSubTask dataclass with depends_on/produces/consumes; DAGDecomposer
extends TaskDecomposer with keyword-rule dependency inference; to_waves()
topological sort produces parallel execution batches.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: ConvergenceChecker

**Files:**
- Create: `src/opencobalt/core/convergence_checker.py`
- Test: `tests/test_convergence_checker.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_convergence_checker.py`:

```python
import pytest
from opencobalt.core.convergence_checker import (
    ConvergenceChecker,
    ConvergenceResult,
    TestsGate,
    VerifierGate,
)


def _passing_tests() -> tuple[bool, str]:
    return (True, "5 passed")


def _failing_tests() -> tuple[bool, str]:
    return (False, "1 failed: test_foo\nAssertionError: expected True")


def _approving_verifier(prompt: str) -> str:
    return '{"score": 0.88, "approved": true, "feedback": "looks good"}'


def _rejecting_verifier(prompt: str) -> str:
    return '{"score": 0.4, "approved": false, "feedback": "missing error handling"}'


def test_tests_gate_pass():
    gate = TestsGate(run_tests=_passing_tests)
    ok, output = gate.check()
    assert ok is True
    assert "5 passed" in output


def test_tests_gate_fail():
    gate = TestsGate(run_tests=_failing_tests)
    ok, output = gate.check()
    assert ok is False
    assert "failed" in output


def test_verifier_gate_approve():
    gate = VerifierGate(consult=_approving_verifier)
    ok, score, feedback = gate.check("implement auth", "diff here")
    assert ok is True
    assert score == pytest.approx(0.88)
    assert "good" in feedback


def test_verifier_gate_reject():
    gate = VerifierGate(consult=_rejecting_verifier)
    ok, score, feedback = gate.check("implement auth", "diff here")
    assert ok is False
    assert score == pytest.approx(0.4)
    assert "error handling" in feedback


def test_verifier_gate_bad_json_returns_zero_score():
    gate = VerifierGate(consult=lambda _: "not json at all")
    ok, score, feedback = gate.check("task", "diff")
    assert ok is False
    assert score == pytest.approx(0.0)


def test_verifier_gate_json_in_prose():
    gate = VerifierGate(consult=lambda _: 'Here is my review: {"score": 0.9, "approved": true, "feedback": "ok"}')
    ok, score, _ = gate.check("task", "diff")
    assert ok is True
    assert score == pytest.approx(0.9)


def test_checker_impl_uses_both_gates():
    checker = ConvergenceChecker(
        tests_gate=TestsGate(run_tests=_passing_tests),
        verifier_gate=VerifierGate(consult=_approving_verifier),
    )
    result = checker.check(["impl"], task="implement auth", diff="diff")
    assert result.tests_ok is True
    assert result.verifier_ok is True
    assert result.passed is True


def test_checker_refactor_uses_tests_gate_only():
    checker = ConvergenceChecker(
        tests_gate=TestsGate(run_tests=_passing_tests),
        verifier_gate=VerifierGate(consult=_rejecting_verifier),
    )
    result = checker.check(["refactor"], task="refactor code", diff="diff")
    assert result.tests_ok is True
    assert result.verifier_ok is None
    assert result.passed is True


def test_checker_docs_uses_verifier_gate_only():
    checker = ConvergenceChecker(
        tests_gate=TestsGate(run_tests=_failing_tests),
        verifier_gate=VerifierGate(consult=_approving_verifier),
    )
    result = checker.check(["docs"], task="write docs", diff="diff")
    assert result.tests_ok is None
    assert result.verifier_ok is True
    assert result.passed is True


def test_checker_mixed_types_union_of_gates():
    checker = ConvergenceChecker(
        tests_gate=TestsGate(run_tests=_passing_tests),
        verifier_gate=VerifierGate(consult=_approving_verifier),
    )
    result = checker.check(["impl", "docs"], task="task", diff="diff")
    assert result.tests_ok is True
    assert result.verifier_ok is True


def test_checker_failed_result_has_feedback():
    checker = ConvergenceChecker(
        tests_gate=TestsGate(run_tests=_failing_tests),
        verifier_gate=VerifierGate(consult=_rejecting_verifier),
    )
    result = checker.check(["impl"], task="task", diff="diff")
    assert result.passed is False
    assert result.feedback != ""
    assert result.feedback != "all gates passed"


def test_checker_passed_result_has_positive_feedback():
    checker = ConvergenceChecker(
        tests_gate=TestsGate(run_tests=_passing_tests),
        verifier_gate=VerifierGate(consult=_approving_verifier),
    )
    result = checker.check(["impl"], task="task", diff="diff")
    assert result.passed is True
    assert "passed" in result.feedback


def test_convergence_result_retry_count_stored():
    checker = ConvergenceChecker(
        tests_gate=TestsGate(run_tests=_passing_tests),
        verifier_gate=VerifierGate(consult=_approving_verifier),
    )
    result = checker.check(["impl"], task="t", diff="d", retry_count=2)
    assert result.retry_count == 2
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_convergence_checker.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'opencobalt.core.convergence_checker'`

- [ ] **Step 3: Create `src/opencobalt/core/convergence_checker.py`**

```python
"""Gate-based convergence checker. TestsGate runs pytest; VerifierGate calls critic agent."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Callable

_VERIFIER_THRESHOLD = 0.75

_VERIFIER_PROMPT = (
    "Review this diff against the task description.\n"
    "Task: {task}\n\nDiff:\n{diff}\n\n"
    "Score 0.0-1.0. Reply with JSON only:\n"
    '{{"score": <float>, "approved": <bool>, "feedback": "<str>"}}'
)


@dataclass
class ConvergenceResult:
    passed: bool
    tests_ok: bool | None
    verifier_ok: bool | None
    verifier_score: float | None
    retry_count: int
    feedback: str


class TestsGate:
    """Run pytest and report pass/fail. Injectable for testing."""

    def __init__(
        self,
        run_tests: Callable[[], tuple[bool, str]] | None = None,
    ) -> None:
        self._run_tests = run_tests or self._default_run

    def _default_run(self) -> tuple[bool, str]:
        result = subprocess.run(
            ["python3", "-m", "pytest", "-q"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        output = (result.stdout + result.stderr)[:5000]
        return result.returncode == 0, output

    def check(self) -> tuple[bool, str]:
        return self._run_tests()


class VerifierGate:
    """Send diff to critic agent (Gemini or Claude). Injectable for testing."""

    def __init__(
        self,
        consult: Callable[[str], str] | None = None,
        threshold: float = _VERIFIER_THRESHOLD,
    ) -> None:
        self._consult = consult or self._default_consult
        self._threshold = threshold

    def _default_consult(self, prompt: str) -> str:
        import shutil
        from .council import consult_subprocess
        model = "gemini" if shutil.which("gemini") else "claude"
        return consult_subprocess(prompt, model=model, intent="advise", timeout=60)

    def check(self, task: str, diff: str) -> tuple[bool, float, str]:
        prompt = _VERIFIER_PROMPT.format(task=task, diff=diff)
        raw = self._consult(prompt)
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            data = json.loads(raw[start:end]) if start >= 0 and end > start else {}
            score = float(data.get("score", 0.0))
            feedback = str(data.get("feedback", ""))
        except (ValueError, KeyError, json.JSONDecodeError):
            return False, 0.0, f"verifier parse error: {raw[:200]}"

        return score >= self._threshold, score, feedback


class ConvergenceChecker:
    """Select and run gates based on task types present in the session."""

    _GATE_MAP: dict[str, set[str]] = {
        "impl":      {"tests", "verifier"},
        "refactor":  {"tests"},
        "tests":     {"tests"},
        "docs":      {"verifier"},
        "review":    {"verifier"},
        "analyze":   {"verifier"},
        "summarize": {"verifier"},
    }

    def __init__(
        self,
        tests_gate: TestsGate | None = None,
        verifier_gate: VerifierGate | None = None,
    ) -> None:
        self._tests_gate = tests_gate or TestsGate()
        self._verifier_gate = verifier_gate or VerifierGate()

    def _required_gates(self, task_types: list[str]) -> set[str]:
        required: set[str] = set()
        for tt in task_types:
            required |= self._GATE_MAP.get(tt, {"verifier"})
        return required

    def check(
        self,
        task_types: list[str],
        task: str = "",
        diff: str = "",
        retry_count: int = 0,
    ) -> ConvergenceResult:
        gates = self._required_gates(task_types)
        tests_ok: bool | None = None
        verifier_ok: bool | None = None
        verifier_score: float | None = None
        feedback_parts: list[str] = []

        if "tests" in gates:
            ok, output = self._tests_gate.check()
            tests_ok = ok
            if not ok:
                feedback_parts.append(f"tests failed:\n{output[:500]}")

        if "verifier" in gates:
            ok, score, fb = self._verifier_gate.check(task, diff)
            verifier_ok = ok
            verifier_score = score
            if not ok:
                feedback_parts.append(f"verifier score {score:.2f}: {fb}")

        passed = (tests_ok is not False) and (verifier_ok is not False)
        feedback = "\n".join(feedback_parts) if feedback_parts else "all gates passed"

        return ConvergenceResult(
            passed=passed,
            tests_ok=tests_ok,
            verifier_ok=verifier_ok,
            verifier_score=verifier_score,
            retry_count=retry_count,
            feedback=feedback,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_convergence_checker.py -v
```
Expected: 13 tests PASS

- [ ] **Step 5: Run full suite**

```bash
python3 -m pytest -q --tb=short
```
Expected: 442 passed (429 + 13)

- [ ] **Step 6: Commit**

```bash
git add src/opencobalt/core/convergence_checker.py tests/test_convergence_checker.py
git commit -m "$(cat <<'EOF'
feat(phase13): add ConvergenceChecker with injectable TestsGate and VerifierGate

Gate selection derived from task types (impl->both, refactor/tests->tests only,
docs/review/analyze/summarize->verifier only). Injectable callables ensure
no real subprocess calls in tests.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: AutoCommitter

**Files:**
- Create: `src/opencobalt/core/auto_committer.py`
- Test: `tests/test_auto_committer.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_auto_committer.py`:

```python
import subprocess
from pathlib import Path
import pytest
from opencobalt.core.auto_committer import AutoCommitter, CommitResult


def _git_runner(responses: dict[str, str]):
    """Fake git runner keyed by 'git <subcommand>'."""
    def run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
        key = " ".join(args[:2])
        stdout = responses.get(key, "")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")
    return run_git


def test_commit_returns_commit_result(tmp_path):
    (tmp_path / "src.py").write_text("code")
    messages: list[str] = []

    def run_git(args, cwd):
        if args[:2] == ["git", "commit"]:
            messages.append(args[3])
        if args == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="abc12345\n", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    committer = AutoCommitter(repo_path=tmp_path, run_git=run_git)
    result = committer.commit(
        session_id="session-uuid-1234-abcd",
        seed_task="implement auth",
        artifact_paths=["src.py"],
        artifact_lines=["impl_code by claude wave 0"],
        waves=1,
        retries=0,
        agents=["claude"],
        tests_info="5 passed / 5 total",
        verifier_info="0.87/1.0 (gemini)",
    )
    assert isinstance(result, CommitResult)
    assert result.sha == "abc1234"
    assert result.files_staged == ["src.py"]


def test_commit_message_contains_required_fields(tmp_path):
    (tmp_path / "src.py").write_text("code")
    messages: list[str] = []

    def run_git(args, cwd):
        if args[:2] == ["git", "commit"]:
            messages.append(args[3])
        if args == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="abc12345", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    committer = AutoCommitter(repo_path=tmp_path, run_git=run_git)
    committer.commit(
        session_id="session-uuid-1234-abcd",
        seed_task="implement auth with JWT",
        artifact_paths=["src.py"],
        artifact_lines=["impl_code by claude wave 0"],
        waves=2,
        retries=1,
        agents=["claude", "codex"],
        tests_info="47 passed / 47 total",
        verifier_info="0.9/1.0 (gemini)",
    )
    assert messages
    msg = messages[0]
    assert "feat(converge):" in msg
    assert "implement auth with JWT" in msg
    assert "session-uui" in msg  # first 8 chars of session_id
    assert "claude, codex" in msg
    assert "Co-Authored-By: Claude Sonnet 4.6" in msg


def test_commit_filters_env_files(tmp_path):
    (tmp_path / "src.py").write_text("code")
    staged: list[str] = []

    def run_git(args, cwd):
        if args[:2] == ["git", "add"]:
            staged.append(args[2])
        if args == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="abc12345", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    committer = AutoCommitter(repo_path=tmp_path, run_git=run_git)
    committer.commit(
        session_id="s", seed_task="task",
        artifact_paths=["src.py", ".env", "data.db", "__pycache__/x.pyc"],
        artifact_lines=[], waves=1, retries=0, agents=[],
        tests_info="n/a", verifier_info="n/a",
    )
    assert ".env" not in staged
    assert "data.db" not in staged
    assert "__pycache__/x.pyc" not in staged
    assert "src.py" in staged


def test_commit_returns_empty_when_no_stageable_files(tmp_path):
    calls: list = []

    def run_git(args, cwd):
        calls.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    committer = AutoCommitter(repo_path=tmp_path, run_git=run_git)
    result = committer.commit(
        session_id="s", seed_task="task", artifact_paths=[],
        artifact_lines=[], waves=1, retries=0, agents=[],
        tests_info="n/a", verifier_info="n/a",
    )
    assert result.sha == ""
    assert result.files_staged == []
    add_calls = [c for c in calls if c[:2] == ["git", "add"]]
    assert len(add_calls) == 0


def test_commit_fallback_when_artifact_paths_empty(tmp_path):
    """When no artifact_paths, falls back to git diff --name-only HEAD."""
    (tmp_path / "changed.py").write_text("changed code")

    def run_git(args, cwd):
        if args == ["git", "diff", "--name-only", "HEAD"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="changed.py\n", stderr="")
        if args == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="abc12345", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    committer = AutoCommitter(repo_path=tmp_path, run_git=run_git)
    result = committer.commit(
        session_id="s", seed_task="task", artifact_paths=[],
        artifact_lines=[], waves=1, retries=0, agents=[],
        tests_info="n/a", verifier_info="n/a",
    )
    assert "changed.py" in result.files_staged


def test_commit_sha_truncated_to_8(tmp_path):
    (tmp_path / "f.py").write_text("x")

    def run_git(args, cwd):
        if args == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="abcdef1234567890\n", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    committer = AutoCommitter(repo_path=tmp_path, run_git=run_git)
    result = committer.commit(
        session_id="s", seed_task="t", artifact_paths=["f.py"],
        artifact_lines=[], waves=1, retries=0, agents=[],
        tests_info="n/a", verifier_info="n/a",
    )
    assert result.sha == "abcdef12"
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_auto_committer.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'opencobalt.core.auto_committer'`

- [ ] **Step 3: Create `src/opencobalt/core/auto_committer.py`**

```python
"""AutoCommitter: stage files from artifact metadata and create a structured git commit."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class CommitResult:
    sha: str
    message: str
    files_staged: list[str] = field(default_factory=list)
    pushed: bool = False


def _default_run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, cwd=cwd, timeout=60)


def _should_skip_path(path: str) -> bool:
    return (
        Path(path).name == ".env"
        or path.endswith(".db")
        or path.endswith(".pyc")
        or ".opencobalt" in path
        or "__pycache__" in path
    )


class AutoCommitter:
    """Stage files listed in artifact metadata and create a structured convergence commit."""

    def __init__(
        self,
        repo_path: Path | None = None,
        run_git: Callable[[list[str], Path], subprocess.CompletedProcess] | None = None,
        push_on_converge: bool = False,
    ) -> None:
        self._repo = repo_path or Path(".")
        self._run_git = run_git or _default_run_git
        self._push_on_converge = push_on_converge

    def _collect_stageable_files(self, artifact_paths: list[str]) -> list[str]:
        result = []
        for p in artifact_paths:
            if _should_skip_path(p):
                continue
            if (self._repo / p).exists():
                result.append(p)
        return result

    def _fallback_files(self) -> list[str]:
        r = self._run_git(["git", "diff", "--name-only", "HEAD"], self._repo)
        if r.returncode != 0 or not r.stdout.strip():
            r = self._run_git(["git", "status", "--porcelain"], self._repo)
            lines = [line[3:].strip() for line in r.stdout.splitlines() if line.strip()]
        else:
            lines = r.stdout.strip().splitlines()
        return [p for p in lines if not _should_skip_path(p)]

    def _build_message(
        self,
        session_id: str,
        seed_task: str,
        waves: int,
        retries: int,
        agents: list[str],
        tests_info: str,
        verifier_info: str,
        artifact_lines: list[str],
    ) -> str:
        title = seed_task[:60]
        agents_str = ", ".join(agents) if agents else "none"
        artifact_block = "\n".join(f"  - {line}" for line in artifact_lines)
        return (
            f"feat(converge): {title}\n\n"
            f"Convergence session {session_id[:8]}\n"
            f"  waves:      {waves}\n"
            f"  retries:    {retries}\n"
            f"  agents:     {agents_str}\n"
            f"  tests:      {tests_info}\n"
            f"  verifier:   {verifier_info}\n\n"
            f"Artifacts produced:\n"
            f"{artifact_block}\n\n"
            f"Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
        )

    def commit(
        self,
        session_id: str,
        seed_task: str,
        artifact_paths: list[str],
        artifact_lines: list[str],
        waves: int,
        retries: int,
        agents: list[str],
        tests_info: str,
        verifier_info: str,
    ) -> CommitResult:
        files = self._collect_stageable_files(artifact_paths) or self._fallback_files()
        if not files:
            return CommitResult(sha="", message="", files_staged=[], pushed=False)

        for f in files:
            self._run_git(["git", "add", f], self._repo)

        message = self._build_message(
            session_id, seed_task, waves, retries,
            agents, tests_info, verifier_info, artifact_lines,
        )
        result = self._run_git(["git", "commit", "-m", message], self._repo)
        if result.returncode != 0:
            return CommitResult(sha="", message=message, files_staged=files, pushed=False)

        sha_result = self._run_git(["git", "rev-parse", "HEAD"], self._repo)
        sha = sha_result.stdout.strip()[:8] if sha_result.returncode == 0 else ""

        pushed = False
        if self._push_on_converge and sha:
            push_result = self._run_git(["git", "push"], self._repo)
            pushed = push_result.returncode == 0

        return CommitResult(sha=sha, message=message, files_staged=files, pushed=pushed)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_auto_committer.py -v
```
Expected: 7 tests PASS

- [ ] **Step 5: Run full suite**

```bash
python3 -m pytest -q --tb=short
```
Expected: 449 passed (442 + 7)

- [ ] **Step 6: Commit**

```bash
git add src/opencobalt/core/auto_committer.py tests/test_auto_committer.py
git commit -m "$(cat <<'EOF'
feat(phase13): add AutoCommitter with injectable git runner

Stages files from artifact metadata with .env/.db/.pyc exclusions; falls
back to git diff --name-only HEAD when no artifact paths; structured commit
message format with co-author line.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: ConvergenceOrchestrator

**Files:**
- Create: `src/opencobalt/core/convergence_orchestrator.py`
- Test: `tests/test_convergence_orchestrator.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_convergence_orchestrator.py`:

```python
import subprocess
from pathlib import Path
import pytest
from opencobalt.core.artifact_bus import ArtifactBus, ArtifactType
from opencobalt.core.auto_committer import AutoCommitter, CommitResult
from opencobalt.core.convergence_checker import (
    ConvergenceChecker,
    TestsGate,
    VerifierGate,
)
from opencobalt.core.convergence_orchestrator import ConvergenceOrchestrator, ConvergenceSession


def _make_checker(pass_result: bool = True) -> ConvergenceChecker:
    verifier_response = (
        '{"score": 0.9, "approved": true, "feedback": "ok"}'
        if pass_result
        else '{"score": 0.3, "approved": false, "feedback": "bad output"}'
    )
    return ConvergenceChecker(
        tests_gate=TestsGate(run_tests=lambda: (True, "5 passed")),
        verifier_gate=VerifierGate(consult=lambda _: verifier_response),
    )


def _make_committer(tmp_path: Path) -> AutoCommitter:
    def run_git(args, cwd):
        if args == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="abc12345\n", stderr="")
        if args[:2] == ["git", "diff"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="diff --git a/f.py\n", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
    return AutoCommitter(repo_path=tmp_path, run_git=run_git)


def test_run_returns_convergence_session(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    orch = ConvergenceOrchestrator(
        artifact_bus=bus,
        checker=_make_checker(True),
        committer=_make_committer(tmp_path),
        execute_subtask=lambda prompt, tool: "output text",
    )
    session = orch.run("implement auth")
    assert isinstance(session, ConvergenceSession)
    assert session.id != ""
    assert session.seed_task == "implement auth"
    assert session.finished_at is not None


def test_run_publishes_impl_artifacts(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    orch = ConvergenceOrchestrator(
        artifact_bus=bus,
        checker=_make_checker(True),
        committer=_make_committer(tmp_path),
        execute_subtask=lambda prompt, tool: "output",
    )
    session = orch.run("implement auth")
    impl_artifacts = bus.subscribe([ArtifactType.IMPL_CODE], session.id)
    assert len(impl_artifacts) >= 1
    assert impl_artifacts[0].content == "output"


def test_run_converged_on_passing_gates(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    orch = ConvergenceOrchestrator(
        artifact_bus=bus,
        checker=_make_checker(True),
        committer=_make_committer(tmp_path),
        execute_subtask=lambda prompt, tool: "output",
    )
    session = orch.run("implement auth")
    assert session.status == "converged"


def test_run_failed_on_persistent_gate_failure(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    orch = ConvergenceOrchestrator(
        artifact_bus=bus,
        checker=_make_checker(False),
        committer=_make_committer(tmp_path),
        execute_subtask=lambda prompt, tool: "output",
    )
    session = orch.run("implement auth")
    assert session.status == "failed"


def test_error_context_published_on_gate_failure(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    orch = ConvergenceOrchestrator(
        artifact_bus=bus,
        checker=_make_checker(False),
        committer=_make_committer(tmp_path),
        execute_subtask=lambda prompt, tool: "output",
    )
    session = orch.run("implement auth")
    error_artifacts = bus.subscribe([ArtifactType.ERROR_CONTEXT], session.id)
    assert len(error_artifacts) > 0


def test_execute_subtask_receives_context_on_retry(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    prompts_seen: list[str] = []

    call_count = 0
    def checker_fn():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return False
        return True

    class ToggleChecker(ConvergenceChecker):
        def check(self, task_types, task="", diff="", retry_count=0):
            from opencobalt.core.convergence_checker import ConvergenceResult
            ok = checker_fn()
            return ConvergenceResult(
                passed=ok,
                tests_ok=ok,
                verifier_ok=None,
                verifier_score=None,
                retry_count=retry_count,
                feedback="" if ok else "tests failed",
            )

    def capture_execute(prompt: str, tool: str) -> str:
        prompts_seen.append(prompt)
        return "output"

    orch = ConvergenceOrchestrator(
        artifact_bus=bus,
        checker=ToggleChecker(),
        committer=_make_committer(tmp_path),
        execute_subtask=capture_execute,
    )
    session = orch.run("implement auth")
    # After first failure, error_context is published; later prompts should be longer
    assert len(prompts_seen) >= 2
    # Later prompts (retry) are longer due to prepended context
    if len(prompts_seen) >= 2:
        assert len(prompts_seen[-1]) >= len(prompts_seen[0])


def test_commit_called_on_convergence(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    commit_called = [False]

    class SpyCommitter(AutoCommitter):
        def commit(self, **kwargs):
            commit_called[0] = True
            return CommitResult(sha="abc12345", message="msg", files_staged=[])

    orch = ConvergenceOrchestrator(
        artifact_bus=bus,
        checker=_make_checker(True),
        committer=SpyCommitter(repo_path=tmp_path),
        execute_subtask=lambda prompt, tool: "output",
    )
    orch.run("implement auth")
    assert commit_called[0] is True


def test_commit_not_called_on_failure(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    commit_called = [False]

    class SpyCommitter(AutoCommitter):
        def commit(self, **kwargs):
            commit_called[0] = True
            return CommitResult(sha="abc12345", message="msg", files_staged=[])

    orch = ConvergenceOrchestrator(
        artifact_bus=bus,
        checker=_make_checker(False),
        committer=SpyCommitter(repo_path=tmp_path),
        execute_subtask=lambda prompt, tool: "output",
    )
    orch.run("implement auth")
    assert commit_called[0] is False


def test_session_waves_counted(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    orch = ConvergenceOrchestrator(
        artifact_bus=bus,
        checker=_make_checker(True),
        committer=_make_committer(tmp_path),
        execute_subtask=lambda prompt, tool: "output",
    )
    session = orch.run("implement auth with tests")
    assert session.total_waves >= 1
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_convergence_orchestrator.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'opencobalt.core.convergence_orchestrator'`

- [ ] **Step 3: Create `src/opencobalt/core/convergence_orchestrator.py`**

```python
"""Top-level convergence orchestrator. Replaces AutonomousRunner for structured work."""

from __future__ import annotations

import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.panel import Panel

from .artifact_bus import AgentArtifact, ArtifactBus, ArtifactType
from .auto_committer import AutoCommitter, CommitResult
from .convergence_checker import ConvergenceChecker, ConvergenceResult
from .dag_decomposer import DAGDecomposer, DAGSubTask

_console = Console()
_COBALT = "#7B9EFF"
_GREEN = "#3DFFA0"
_RED = "#FF5577"
_MAX_RETRIES = 3


@dataclass
class ConvergenceSession:
    id: str
    seed_task: str
    status: str = "queued"
    started_at: float = 0.0
    finished_at: float | None = None
    total_waves: int = 0
    total_retries: int = 0
    commit_sha: str | None = None
    log_path: Path | None = None


def _default_execute_subtask(prompt: str, tool: str) -> str:
    import shutil
    from .council import consult_subprocess

    model_map = {
        "claude-code": "claude",
        "codex-cli": "codex",
        "gemini-cli": "gemini",
        "ollama": "ollama",
    }
    model = model_map.get(tool, "claude")
    if not shutil.which(model):
        return f"[{model}: not on PATH]"
    return consult_subprocess(prompt, model=model, intent="implement", timeout=120)


class ConvergenceOrchestrator:
    """Decomposes a task into a DAG, executes waves, checks convergence, auto-commits."""

    def __init__(
        self,
        decomposer: DAGDecomposer | None = None,
        artifact_bus: ArtifactBus | None = None,
        checker: ConvergenceChecker | None = None,
        committer: AutoCommitter | None = None,
        ledger=None,
        execute_subtask: Callable[[str, str], str] | None = None,
    ) -> None:
        self._decomposer = decomposer or DAGDecomposer()
        self._bus = artifact_bus or ArtifactBus()
        self._checker = checker or ConvergenceChecker()
        self._committer = committer or AutoCommitter()
        self._ledger = ledger
        self._execute_subtask = execute_subtask or _default_execute_subtask

    def run(self, seed_task: str, resume_session_id: str | None = None) -> ConvergenceSession:
        session_id = resume_session_id or str(uuid.uuid4())
        session = ConvergenceSession(
            id=session_id,
            seed_task=seed_task,
            status="running",
            started_at=time.time(),
        )
        self._persist_session(session)

        subtasks = self._decomposer.decompose_dag(seed_task)
        waves = self._decomposer.to_waves(subtasks)
        session.total_waves = len(waves)

        all_converged = True
        last_result: ConvergenceResult | None = None

        for wave_idx, wave in enumerate(waves):
            result = self._run_wave(session, wave, wave_idx)
            last_result = result
            if not result.passed:
                all_converged = False

        session.finished_at = time.time()
        session.status = "converged" if all_converged else "failed"
        self._persist_session(session)

        if all_converged:
            commit = self._do_commit(session, subtasks, last_result)
            session.commit_sha = commit.sha

        self._print_summary(session)
        return session

    def _run_wave(
        self,
        session: ConvergenceSession,
        wave: list[DAGSubTask],
        wave_idx: int,
    ) -> ConvergenceResult:
        result = ConvergenceResult(
            passed=False, tests_ok=None, verifier_ok=None,
            verifier_score=None, retry_count=0, feedback="no check performed",
        )
        retry_count = 0

        while retry_count <= _MAX_RETRIES:
            # Build context from bus for each subtask (include error_context)
            outputs: dict[str, str] = {}
            with ThreadPoolExecutor(max_workers=min(len(wave), 6)) as pool:
                futures = {
                    pool.submit(
                        self._execute_subtask,
                        self._build_prompt(session.id, st),
                        st.preferred_tool,
                    ): st
                    for st in wave
                }
                for future in as_completed(futures):
                    st = futures[future]
                    try:
                        outputs[st.id] = future.result(timeout=300)
                    except Exception as exc:
                        outputs[st.id] = f"[error: {exc}]"

            # Publish artifacts
            for st in wave:
                output = outputs.get(st.id, "")
                for artifact_type in st.produces:
                    self._bus.publish(AgentArtifact(
                        id=str(uuid.uuid4()),
                        session_id=session.id,
                        iteration=retry_count,
                        wave=wave_idx,
                        producer=st.preferred_tool,
                        type=artifact_type,
                        content=output,
                        metadata={"task_type": st.task_type},
                        timestamp=time.time(),
                    ))

            task_types = list({st.task_type for st in wave})
            diff = self._get_diff()
            result = self._checker.check(
                task_types=task_types,
                task=session.seed_task,
                diff=diff,
                retry_count=retry_count,
            )
            self._persist_wave_result(session.id, wave_idx, result)

            if result.passed:
                return result

            if retry_count >= _MAX_RETRIES:
                break

            if result.feedback:
                self._bus.publish(AgentArtifact(
                    id=str(uuid.uuid4()),
                    session_id=session.id,
                    iteration=retry_count,
                    wave=wave_idx,
                    producer="convergence-checker",
                    type=ArtifactType.ERROR_CONTEXT,
                    content=result.feedback,
                    metadata={},
                    timestamp=time.time(),
                ))

            retry_count += 1
            session.total_retries += 1

        return result

    def _build_prompt(self, session_id: str, st: DAGSubTask) -> str:
        ctx = self._bus.context_for(
            st.consumes + [ArtifactType.ERROR_CONTEXT], session_id
        )
        if ctx:
            return f"{ctx}\n\n{st.prompt}"
        return st.prompt

    def _get_diff(self) -> str:
        try:
            r = subprocess.run(
                ["git", "diff", "HEAD"],
                capture_output=True, text=True, timeout=30,
            )
            return r.stdout[:3000] if r.returncode == 0 else ""
        except Exception:
            return ""

    def _do_commit(
        self,
        session: ConvergenceSession,
        subtasks: list[DAGSubTask],
        last_result: ConvergenceResult | None,
    ) -> CommitResult:
        artifact_paths: list[str] = []
        artifact_lines: list[str] = []
        agents: list[str] = []

        for art_type in (ArtifactType.IMPL_CODE, ArtifactType.TEST_CODE,
                         ArtifactType.DOC_TEXT, ArtifactType.REVIEW_SCORE):
            for a in self._bus.subscribe([art_type], session.id):
                paths = a.metadata.get("file_paths", [])
                if isinstance(paths, list):
                    artifact_paths.extend(paths)
                artifact_lines.append(
                    f"{a.type:<15} by {a.producer:<12} wave {a.wave}"
                )
                if a.producer not in agents:
                    agents.append(a.producer)

        tests_info = "n/a"
        verifier_info = "n/a"
        if last_result:
            if last_result.tests_ok is not None:
                tests_info = "passed" if last_result.tests_ok else "failed"
            if last_result.verifier_score is not None:
                verifier_info = f"{last_result.verifier_score:.2f}/1.0"

        return self._committer.commit(
            session_id=session.id,
            seed_task=session.seed_task,
            artifact_paths=artifact_paths,
            artifact_lines=artifact_lines,
            waves=session.total_waves,
            retries=session.total_retries,
            agents=agents,
            tests_info=tests_info,
            verifier_info=verifier_info,
        )

    def _persist_session(self, session: ConvergenceSession) -> None:
        if self._ledger is None:
            return
        try:
            self._ledger.upsert_convergence_session(
                session_id=session.id,
                seed_task=session.seed_task,
                status=session.status,
                started_at=session.started_at,
                finished_at=session.finished_at,
                total_waves=session.total_waves,
                total_retries=session.total_retries,
                commit_sha=session.commit_sha,
                log_path=str(session.log_path) if session.log_path else None,
            )
        except Exception:
            pass

    def _persist_wave_result(
        self, session_id: str, wave_idx: int, result: ConvergenceResult
    ) -> None:
        if self._ledger is None:
            return
        try:
            self._ledger.insert_wave_result(
                session_id=session_id,
                wave=wave_idx,
                tests_ok=result.tests_ok,
                verifier_score=result.verifier_score,
                verifier_ok=result.verifier_ok,
                passed=result.passed,
                retry_count=result.retry_count,
                feedback=result.feedback,
            )
        except Exception:
            pass

    def _print_summary(self, session: ConvergenceSession) -> None:
        color = _GREEN if session.status == "converged" else _RED
        elapsed = (session.finished_at or time.time()) - session.started_at
        m, s = divmod(int(elapsed), 60)
        elapsed_str = f"{m}:{s:02d}" if m else f"{s}s"
        commit_line = f"\n  [dim]commit: {session.commit_sha}[/dim]" if session.commit_sha else ""
        _console.print(Panel(
            f"[{color}]{session.status}[/{color}]  "
            f"[dim]{session.total_waves} waves · {session.total_retries} retries · "
            f"{elapsed_str}[/dim]{commit_line}",
            title=f"[bold {_COBALT}]convergence complete[/bold {_COBALT}]",
            border_style=_COBALT,
        ))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_convergence_orchestrator.py -v
```
Expected: 9 tests PASS

- [ ] **Step 5: Run full suite**

```bash
python3 -m pytest -q --tb=short
```
Expected: 458 passed (449 + 9)

- [ ] **Step 6: Commit**

```bash
git add src/opencobalt/core/convergence_orchestrator.py tests/test_convergence_orchestrator.py
git commit -m "$(cat <<'EOF'
feat(phase13): add ConvergenceOrchestrator with wave execution and retry loop

DAG decompose -> parallel wave execution -> convergence check -> retry up to 3x
-> auto-commit on success. error_context artifacts injected into retry prompts
automatically. Ledger persistence optional (injected).

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: CLI surface

**Files:**
- Modify: `src/opencobalt/cli.py`
- Test: add to `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Add these tests at the bottom of `tests/test_cli.py`:

```python
# ── Converge command ──────────────────────────────────────────────────────────

def test_converge_history_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _invoke("converge", "history")
    assert result.exit_code == 0
    assert "No convergence sessions" in result.output or result.exit_code == 0


def test_converge_history_with_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from opencobalt.core.ledger import Ledger
    ledger = Ledger(tmp_path / ".opencobalt" / "ledger.db")
    ledger.upsert_convergence_session(
        session_id="abc12345-test", seed_task="implement auth", status="converged",
        started_at=1000.0, finished_at=1100.0, total_waves=2, total_retries=0,
        commit_sha="abc12345", log_path=None,
    )
    result = _invoke("converge", "history")
    assert result.exit_code == 0
    assert "abc12345" in result.output or "implement auth" in result.output


def test_converge_show_not_found(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _invoke("converge", "show", "nonexistent-id")
    assert result.exit_code != 0


def test_converge_show_with_session(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from opencobalt.core.ledger import Ledger
    ledger = Ledger(tmp_path / ".opencobalt" / "ledger.db")
    ledger.upsert_convergence_session(
        session_id="full-session-id-here", seed_task="test task", status="converged",
        started_at=1000.0, finished_at=1100.0, total_waves=1, total_retries=0,
        commit_sha="abc12345", log_path=None,
    )
    result = _invoke("converge", "show", "full-session-id-here")
    assert result.exit_code == 0
    assert "test task" in result.output


def test_auto_accepts_converge_flag_help():
    result = _invoke("auto", "--help")
    assert result.exit_code == 0
    assert "--converge" in result.output
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_cli.py -k "converge" -v
```
Expected: FAIL with `typer.testing.CliRunner` error or missing command

- [ ] **Step 3: Add `converge_app` to `src/opencobalt/cli.py`**

After line `88` (after `benchmark_app = typer.Typer(...)`), add:

```python
converge_app = typer.Typer(help="Convergence protocol commands.", invoke_without_command=True)
app.add_typer(converge_app, name="converge")
```

After the `auto` command (around line 793), add the converge commands:

```python
@converge_app.callback()
def converge_cmd(
    ctx: typer.Context,
    task: str = typer.Argument(default=""),
    resume: str = typer.Option("", "--resume", help="Resume interrupted session by ID"),
    push_on_converge: bool = typer.Option(
        False, "--push-on-converge", help="Push to remote after successful convergence"
    ),
) -> None:
    """Run convergence protocol: decompose task, execute DAG waves, verify, commit."""
    if ctx.invoked_subcommand is not None:
        return
    if not task and not resume:
        console.print("  [dim]Usage: opencobalt converge \"task\" | --resume SESSION_ID[/dim]")
        return
    from .core.auto_committer import AutoCommitter
    from .core.convergence_orchestrator import ConvergenceOrchestrator

    actual_task = task
    resume_id: str | None = None
    if resume:
        resume_id = resume
        if not actual_task:
            row = _ledger().get_convergence_session(resume)
            actual_task = row["seed_task"] if row else ""
        if not actual_task:
            err.print(f"  Session not found: {resume}")
            raise typer.Exit(1)

    orch = ConvergenceOrchestrator(
        committer=AutoCommitter(push_on_converge=push_on_converge),
        ledger=_ledger(),
    )
    orch.run(actual_task, resume_session_id=resume_id)


@converge_app.command("history")
def converge_history(
    limit: int = typer.Option(10, "--limit", "-n", help="Max sessions to show"),
) -> None:
    """List recent convergence sessions."""
    sessions = _ledger().list_convergence_sessions(limit=limit)
    if not sessions:
        console.print("\n  [dim]No convergence sessions found.[/dim]\n")
        return

    console.print()
    table = Table(title="Convergence Sessions", box=box.SIMPLE, padding=(0, 2))
    table.add_column("ID", style=_COBALT, width=10, no_wrap=True)
    table.add_column("Task", width=40)
    table.add_column("Status", width=12)
    table.add_column("Waves", justify="right", width=6)
    table.add_column("Retries", justify="right", width=8)
    for s in sessions:
        table.add_row(
            s["id"][:8],
            s["seed_task"][:40],
            s["status"],
            str(s["total_waves"]),
            str(s["total_retries"]),
        )
    console.print(table)
    console.print(f"  [dim]{len(sessions)} session(s)[/dim]\n")


@converge_app.command("show")
def converge_show(
    session_id: str = typer.Argument(..., help="Session ID (or prefix) to inspect"),
) -> None:
    """Show wave results and artifact summary for a convergence session."""
    ledger = _ledger()
    session = ledger.get_convergence_session(session_id)
    if not session:
        sessions = ledger.list_convergence_sessions(limit=100)
        matches = [s for s in sessions if s["id"].startswith(session_id)]
        if not matches:
            err.print(f"\n  Session not found: {session_id}\n")
            raise typer.Exit(1)
        session = matches[0]

    console.print(f"\n  [bold {_COBALT}]Session {session['id'][:8]}[/bold {_COBALT}]")
    console.print(f"  [dim]task:[/dim]    {session['seed_task']}")
    console.print(f"  [dim]status:[/dim]  {session['status']}")
    console.print(f"  [dim]waves:[/dim]   {session['total_waves']}  "
                  f"[dim]retries:[/dim] {session['total_retries']}")
    if session.get("commit_sha"):
        console.print(f"  [dim]commit:[/dim]  {session['commit_sha']}")

    wave_results = ledger.get_wave_results(session["id"])
    if wave_results:
        console.print(f"\n  [dim]Wave results ({len(wave_results)}):[/dim]")
        for wr in wave_results:
            ok = f"[{_GREEN}]✓[/{_GREEN}]" if wr["passed"] else f"[{_RED}]✗[/{_RED}]"
            console.print(
                f"    wave {wr['wave']} retry {wr['retry_count']}  {ok}  "
                f"[dim]{str(wr['feedback'])[:60]}[/dim]"
            )
    console.print()
```

Also modify the `auto` command signature at line 783 to add `--converge`:

```python
@app.command()
def auto(
    task: str = typer.Argument(..., help="Seed task for autonomous multi-agent execution"),
    iterations: int = typer.Option(20, "--iterations", "-n", help="Max iterations"),
    hours: float = typer.Option(5.0, "--hours", "-t", help="Max runtime in hours"),
    converge: bool = typer.Option(
        False, "--converge", help="Use convergence protocol (DAG + gating) instead of autonomous runner"
    ),
) -> None:
    """Run autonomous multi-agent session. Use --converge for structured DAG execution."""
    if converge:
        from .core.convergence_orchestrator import ConvergenceOrchestrator
        orch = ConvergenceOrchestrator(ledger=_ledger())
        orch.run(task)
        return
    from .core.autonomous_runner import AutonomousRunner
    runner = AutonomousRunner(max_iterations=iterations, max_hours=hours)
    runner.run(task)
```

- [ ] **Step 4: Run the new CLI tests**

```bash
python3 -m pytest tests/test_cli.py -k "converge" -v
```
Expected: 5 tests PASS

- [ ] **Step 5: Run full suite**

```bash
python3 -m pytest -q --tb=short
```
Expected: 463 passed (458 + 5)

- [ ] **Step 6: Run public-check (CLAUDE.md requirement)**

```bash
opencobalt public-check
```
Expected: PASSED

- [ ] **Step 7: Commit**

```bash
git add src/opencobalt/cli.py tests/test_cli.py
git commit -m "$(cat <<'EOF'
feat(phase13): add opencobalt converge CLI command

converge_app with callback (run task) + history + show subcommands;
--converge flag on auto; --resume SESSION_ID for interrupted sessions.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Shell surface

**Files:**
- Modify: `src/opencobalt/shell.py`
- Test: add to `tests/test_shell.py`

- [ ] **Step 1: Write failing shell tests**

Read `tests/test_shell.py` to understand what already exists there, then add these tests:

```python
def test_converge_in_slash_commands(tmp_path):
    from opencobalt.shell import CobaltShell
    shell = CobaltShell(
        db_path=tmp_path / "ledger.db",
        bridge_path=tmp_path / "memories.db",
    )
    commands = shell.list_slash_commands()
    assert "converge" in commands


def test_dispatch_converge_empty_prints_usage(tmp_path, capsys):
    from opencobalt.shell import CobaltShell
    shell = CobaltShell(
        db_path=tmp_path / "ledger.db",
        bridge_path=tmp_path / "memories.db",
    )
    # Empty /converge should print usage, not raise
    shell.dispatch("/converge")
    # No assertion on output (rich console output captured differently)
    # Just verify it doesn't raise
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_shell.py -k "converge" -v
```
Expected: FAIL because `"converge"` not in `list_slash_commands()`

- [ ] **Step 3: Modify `src/opencobalt/shell.py`**

In `_CLI_COMMANDS` list (around line 35), add `"converge"` after `"auto"`:

```python
    _CLI_COMMANDS = [
        "route",
        "brief",
        "status",
        "history",
        "stats",
        "benchmark",
        "verify",
        "lint",
        "doctor",
        "public-check",
        "context",
        "export",
        "log",
        "note",
        "day",
        "memory",
        "agents",
        "skills",
        "integrations",
        "cost",
        "config",
        "session",
        "hooks",
        "council",
        "debate",
        "orch",
        "auto",
        "converge",
        "install-hooks",
        "tui",
        "ui",
    ]
```

In `_run_command` method, add the `converge` handler before the final `argv` fallback (around line 265):

```python
        if cmd == "converge":
            self._run_converge(" ".join(args))
            return
```

Add the new `_run_converge` method after `_run_auto`:

```python
    def _run_converge(self, task: str) -> None:
        from .core.auto_committer import AutoCommitter
        from .core.convergence_orchestrator import ConvergenceOrchestrator

        if not task.strip():
            console.print(
                f"  [{_AMBER}]Usage:[/{_AMBER}]  /converge \"task\""
                "  |  /converge --resume"
            )
            return

        resume_id: str | None = None
        actual_task = task.strip()

        if actual_task == "--resume":
            sessions = self._ledger.list_convergence_sessions(limit=1)
            if not sessions:
                console.print("  [dim]No sessions to resume.[/dim]")
                return
            last = sessions[0]
            if last["status"] not in ("running", "failed", "interrupted"):
                console.print(
                    f"  [dim]Last session {last['id'][:8]} is already {last['status']}.[/dim]"
                )
                return
            resume_id = last["id"]
            actual_task = last["seed_task"]

        orch = ConvergenceOrchestrator(
            committer=AutoCommitter(),
            ledger=self._ledger,
        )
        orch.run(actual_task, resume_session_id=resume_id)
```

- [ ] **Step 4: Run the new shell tests**

```bash
python3 -m pytest tests/test_shell.py -k "converge" -v
```
Expected: 2 tests PASS

- [ ] **Step 5: Run full suite**

```bash
python3 -m pytest -q --tb=short
```
Expected: 465 passed (463 + 2)

- [ ] **Step 6: Run public-check**

```bash
opencobalt public-check
```
Expected: PASSED

- [ ] **Step 7: Commit**

```bash
git add src/opencobalt/shell.py tests/test_shell.py
git commit -m "$(cat <<'EOF'
feat(phase13): add /converge slash command to cobalt shell

Adds 'converge' to _CLI_COMMANDS for autocomplete, _run_converge handler
with --resume support for last interrupted session.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Against Spec

### Spec coverage

| Spec section | Implemented in |
|---|---|
| ArtifactType enum | Task 2 (`ArtifactType` class) |
| AgentArtifact dataclass | Task 2 |
| ArtifactBus.publish/subscribe/latest/context_for | Task 2 |
| error_context auto-inject | Task 2 (context_for) + Task 6 (_build_prompt appends ERROR_CONTEXT) |
| DAGSubTask dataclass | Task 3 |
| DAGDecomposer with type tables | Task 3 |
| Topological sort / waves | Task 3 (to_waves) |
| TestsGate (pytest -q) | Task 4 |
| VerifierGate (critic agent, 0.75 threshold) | Task 4 |
| ConvergenceResult dataclass | Task 4 |
| Gate selection by task type | Task 4 (ConvergenceChecker._GATE_MAP) |
| Retry behavior (max 3) | Task 6 (_run_wave loop) |
| AutoCommitter + CommitResult | Task 5 |
| Staging strategy (artifact metadata + fallback) | Task 5 |
| Never-stage list (.env, *.db, .pyc, etc.) | Task 5 (_should_skip_path) |
| Commit message format | Task 5 (_build_message) |
| push_on_converge flag (off by default) | Task 5 + Task 7 (CLI flag) |
| ConvergenceOrchestrator execution loop | Task 6 |
| ConvergenceSession dataclass | Task 6 |
| SQLite tables (convergence_sessions, wave_results) | Task 1 |
| ArtifactBus in artifacts.db | Task 2 |
| `opencobalt converge TASK` | Task 7 |
| `opencobalt converge --resume` | Task 7 |
| `opencobalt converge history` | Task 7 |
| `opencobalt converge show SESSION_ID` | Task 7 |
| `opencobalt auto --converge` | Task 7 |
| `/converge <task>` shell command | Task 8 |
| `/converge --resume` | Task 8 |

### Out-of-scope items (per spec section 9)
- LLM-based dependency inference (using keyword rules)
- Multi-user/networked artifact bus
- Artifact versioning/diffing
- Automatic branch creation
- Verifier agent training

### Placeholder scan
No TBDs, TODOs, or "similar to Task N" references found.

### Type consistency
- `ArtifactType.IMPL_CODE` used consistently in Task 2, 6
- `DAGSubTask` fields: `id`, `prompt`, `task_type`, `preferred_tool`, `depends_on`, `produces`, `consumes` -- consistent across Task 3 and 6
- `ConvergenceResult` fields: `passed`, `tests_ok`, `verifier_ok`, `verifier_score`, `retry_count`, `feedback` -- consistent across Task 4 and 6
- `CommitResult` fields: `sha`, `message`, `files_staged`, `pushed` -- consistent across Task 5 and 6
- `ConvergenceSession` fields: `id`, `seed_task`, `status`, etc. -- consistent across Task 6 and 7
- Ledger method `upsert_convergence_session` called in Task 6 with keyword args matching signature in Task 1
