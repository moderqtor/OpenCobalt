# Phase 15: Intelligence Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a telemetry capture, multi-dimensional scoring, and optional markdown export layer to every OpenCobalt run.

**Architecture:** A `TelemetrySession` is created at each run entry point and passed through the call chain; components call thin `record_*` methods on it. When the run ends, `ScoringEngine` computes heuristics and calls `OllamaJudge` (via subprocess) which returns category scores as JSON. Everything lands in `.opencobalt/telemetry.db`. An optional `MarkdownExporter` writes timestamped `.md` files to a user-configured directory.

**Tech Stack:** Python, SQLite (sqlite3), subprocess (Ollama via CLI), typer (CLI), pytest + tmp_path (tests).

---

## File Map

**New files:**
- `src/opencobalt/core/telemetry.py` — `TelemetryStore`, `TelemetrySession`, schema
- `src/opencobalt/core/ollama_judge.py` — `OllamaJudge`, prompt, subprocess, parse, fallback
- `src/opencobalt/core/scoring_engine.py` — `ScoringEngine`, heuristics, weight table
- `src/opencobalt/core/markdown_exporter.py` — `MarkdownExporter`, file render, related links
- `tests/test_telemetry.py`
- `tests/test_ollama_judge.py`
- `tests/test_scoring_engine.py`
- `tests/test_markdown_exporter.py`

**Modified files:**
- `src/opencobalt/cli.py` — add `telemetry_app` typer group + 6 commands + `--telemetry` flag on `benchmark_status`
- `src/opencobalt/core/overlay.py` — create session in `handle_prompt()`, call `ScoringEngine` after run
- `src/opencobalt/core/artifact_bus.py` — `publish()` calls `session.record_artifact()` when session present
- `src/opencobalt/core/convergence_checker.py` — `check()` calls `session.record_gate_pass/fail()` when session present
- `src/opencobalt/core/convergence_orchestrator.py` — accept optional `telemetry_session`, record retries and tool calls
- `src/opencobalt/core/autonomy_engine.py` — accept optional `telemetry_session` in `start()` and `resume()`
- `src/opencobalt/core/mission.py` — accept optional `telemetry_session` in `plan()`
- `src/opencobalt/core/capability_index.py` — accept optional `telemetry_session` in `discover()`
- `src/opencobalt/core/usage_optimizer.py` — accept optional `telemetry_session` in `choose_tool()`

---

### Task 1: TelemetryStore — schema and write path

**Files:**
- Create: `src/opencobalt/core/telemetry.py`
- Create: `tests/test_telemetry.py`

- [ ] **Step 1: Write the failing test for schema initialisation**

```python
# tests/test_telemetry.py
import sqlite3
from pathlib import Path
from opencobalt.core.telemetry import TelemetryStore


def test_schema_creates_three_tables(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.db")
    conn = sqlite3.connect(tmp_path / "telemetry.db")
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "telemetry_runs" in tables
    assert "telemetry_events" in tables
    assert "telemetry_scores" in tables
```

- [ ] **Step 2: Run test to confirm it fails**

```
pytest tests/test_telemetry.py::test_schema_creates_three_tables -v
```
Expected: `FAILED` — `ModuleNotFoundError` or `ImportError`.

- [ ] **Step 3: Create `src/opencobalt/core/telemetry.py` with schema and `TelemetryStore.__init__`**

```python
"""Telemetry capture store for OpenCobalt runs."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry_runs (
    id                   TEXT PRIMARY KEY,
    run_type             TEXT NOT NULL,
    seed_prompt          TEXT NOT NULL,
    agent_id             TEXT NOT NULL,
    subagent_id          TEXT,
    model_used           TEXT NOT NULL DEFAULT '',
    started_at           REAL NOT NULL,
    finished_at          REAL,
    status               TEXT NOT NULL,
    raw_output           TEXT,
    token_count_in       INTEGER,
    token_count_out      INTEGER,
    tool_calls_json      TEXT NOT NULL DEFAULT '[]',
    skills_used_json     TEXT NOT NULL DEFAULT '[]',
    connectors_used_json TEXT NOT NULL DEFAULT '[]',
    artifacts_produced   INTEGER NOT NULL DEFAULT 0,
    retry_count          INTEGER NOT NULL DEFAULT 0,
    latency_ms           INTEGER,
    summary              TEXT
);

CREATE TABLE IF NOT EXISTS telemetry_events (
    id           TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    timestamp    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS telemetry_scores (
    id                   TEXT PRIMARY KEY,
    run_id               TEXT NOT NULL UNIQUE,
    scored_at            TEXT NOT NULL,
    judge                TEXT NOT NULL,
    overall              INTEGER NOT NULL,
    output_quality       INTEGER,
    prompt_adherence     INTEGER,
    novel_ideation       INTEGER,
    context_handling     INTEGER,
    token_efficiency     INTEGER,
    latency_score        INTEGER,
    tool_appropriateness INTEGER,
    task_decomposition   INTEGER,
    agent_selection      INTEGER,
    convergence_quality  INTEGER,
    judge_reasoning      TEXT,
    heuristics_json      TEXT NOT NULL DEFAULT '{}'
);
"""


class TelemetryStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
```

- [ ] **Step 4: Run test to confirm it passes**

```
pytest tests/test_telemetry.py::test_schema_creates_three_tables -v
```
Expected: `PASSED`.

- [ ] **Step 5: Write failing tests for `start_run`, `add_event`, `finish_run`**

```python
def test_start_run_returns_session(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="route", seed_prompt="summarize logs", agent_id="claude-code")
    assert session.run_id
    run = store.get_run(session.run_id)
    assert run["status"] == "running"
    assert run["run_type"] == "route"
    assert run["seed_prompt"] == "summarize logs"


def test_add_event_persists(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="route", seed_prompt="x", agent_id="claude-code")
    store.add_event(session.run_id, "tool_use", {"tool": "pytest"})
    events = store.list_events(session.run_id)
    assert len(events) == 1
    assert events[0]["event_type"] == "tool_use"
    assert json.loads(events[0]["payload_json"])["tool"] == "pytest"


def test_finish_run_updates_status(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="route", seed_prompt="x", agent_id="claude-code")
    store.add_event(session.run_id, "retry", {"reason": "gate failed"})
    store.add_event(session.run_id, "artifact", {"type": "code", "id": "abc"})
    store.finish_run(session.run_id, "complete")
    run = store.get_run(session.run_id)
    assert run["status"] == "complete"
    assert run["retry_count"] == 1
    assert run["artifacts_produced"] == 1
    assert run["latency_ms"] is not None
```

- [ ] **Step 6: Implement `start_run`, `get_run`, `add_event`, `list_events`, `finish_run`**

Add these methods to `TelemetryStore` in `telemetry.py`:

```python
    def start_run(
        self,
        *,
        run_type: str,
        seed_prompt: str,
        agent_id: str,
        subagent_id: str | None = None,
        model_used: str = "",
    ) -> "TelemetrySession":
        run_id = str(uuid.uuid4())
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO telemetry_runs
                   (id, run_type, seed_prompt, agent_id, subagent_id, model_used, started_at, status)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (run_id, run_type, seed_prompt, agent_id, subagent_id, model_used, now, "running"),
            )
        return TelemetrySession(run_id, self)

    def get_run(self, run_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM telemetry_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return dict(row) if row else None

    def add_event(self, run_id: str, event_type: str, payload: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO telemetry_events (id, run_id, event_type, payload_json, timestamp) VALUES (?,?,?,?,?)",
                (str(uuid.uuid4()), run_id, event_type, json.dumps(payload), time.time()),
            )

    def list_events(self, run_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM telemetry_events WHERE run_id = ? ORDER BY timestamp",
                (run_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def finish_run(self, run_id: str, status: str) -> None:
        now = time.time()
        events = self.list_events(run_id)

        def _payloads(etype: str) -> list[dict]:
            return [json.loads(e["payload_json"]) for e in events if e["event_type"] == etype]

        tool_calls = list({p.get("tool", "") for p in _payloads("tool_use")} - {""})
        skills = list({p.get("skill_id", "") for p in _payloads("skill_use")} - {""})
        connectors = list({p.get("connector_id", "") for p in _payloads("connector_use")} - {""})
        artifacts = sum(1 for e in events if e["event_type"] == "artifact")
        retries = sum(1 for e in events if e["event_type"] == "retry")

        run = self.get_run(run_id)
        started = run["started_at"] if run else now
        latency_ms = int((now - started) * 1000)

        with self._connect() as conn:
            conn.execute(
                """UPDATE telemetry_runs SET
                   finished_at=?, status=?, tool_calls_json=?, skills_used_json=?,
                   connectors_used_json=?, artifacts_produced=?, retry_count=?, latency_ms=?
                   WHERE id=?""",
                (
                    now, status,
                    json.dumps(tool_calls), json.dumps(skills), json.dumps(connectors),
                    artifacts, retries, latency_ms, run_id,
                ),
            )

    def set_raw_output(self, run_id: str, output: str, *, token_count_out: int | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE telemetry_runs SET raw_output=?, token_count_out=? WHERE id=?",
                (output, token_count_out, run_id),
            )

    def set_summary(self, run_id: str, summary: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE telemetry_runs SET summary=? WHERE id=?", (summary, run_id)
            )
```

- [ ] **Step 7: Run tests**

```
pytest tests/test_telemetry.py -v
```
Expected: all 4 tests `PASSED`.

- [ ] **Step 8: Write failing tests for `save_score`, `get_score`, `list_runs`**

```python
def test_save_and_get_score(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="route", seed_prompt="x", agent_id="claude-code")
    store.finish_run(session.run_id, "complete")
    score = {
        "run_id": session.run_id,
        "scored_at": "2026-06-07T00:00:00Z",
        "judge": "heuristic",
        "overall": 72,
        "output_quality": 80,
        "prompt_adherence": 75,
        "novel_ideation": 50,
        "context_handling": 50,
        "token_efficiency": 70,
        "latency_score": 85,
        "tool_appropriateness": 60,
        "task_decomposition": 50,
        "agent_selection": 50,
        "convergence_quality": 95,
        "judge_reasoning": "Decent output.",
        "heuristics": {"retry_count": 0},
    }
    store.save_score(score)
    result = store.get_score(session.run_id)
    assert result["overall"] == 72
    assert result["judge"] == "heuristic"
    run = store.get_run(session.run_id)
    assert run["status"] == "scored"


def test_list_runs(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    for i in range(3):
        s = store.start_run(run_type="route", seed_prompt=f"task {i}", agent_id="claude-code")
        store.finish_run(s.run_id, "complete")
    runs = store.list_runs(limit=10)
    assert len(runs) == 3

    runs_filtered = store.list_runs(run_type="route")
    assert len(runs_filtered) == 3

    runs_none = store.list_runs(run_type="converge")
    assert len(runs_none) == 0
```

- [ ] **Step 9: Implement `save_score`, `get_score`, `list_runs`**

```python
    def save_score(self, score: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO telemetry_scores
                   (id, run_id, scored_at, judge, overall, output_quality, prompt_adherence,
                    novel_ideation, context_handling, token_efficiency, latency_score,
                    tool_appropriateness, task_decomposition, agent_selection, convergence_quality,
                    judge_reasoning, heuristics_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()),
                    score["run_id"], score["scored_at"], score["judge"], score["overall"],
                    score.get("output_quality"), score.get("prompt_adherence"),
                    score.get("novel_ideation"), score.get("context_handling"),
                    score.get("token_efficiency"), score.get("latency_score"),
                    score.get("tool_appropriateness"), score.get("task_decomposition"),
                    score.get("agent_selection"), score.get("convergence_quality"),
                    score.get("judge_reasoning"),
                    json.dumps(score.get("heuristics", {})),
                ),
            )
        with self._connect() as conn:
            conn.execute(
                "UPDATE telemetry_runs SET status='scored' WHERE id=?", (score["run_id"],)
            )

    def get_score(self, run_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM telemetry_scores WHERE run_id=?", (run_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_runs(
        self,
        limit: int = 50,
        agent_id: str | None = None,
        run_type: str | None = None,
    ) -> list[dict]:
        query = "SELECT * FROM telemetry_runs"
        params: list = []
        conditions: list[str] = []
        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)
        if run_type:
            conditions.append("run_type = ?")
            params.append(run_type)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_leaderboard(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT r.agent_id,
                          COUNT(*) AS total,
                          AVG(s.overall) AS avg_overall,
                          AVG(s.output_quality) AS avg_output_quality,
                          AVG(s.token_efficiency) AS avg_token_efficiency,
                          AVG(s.prompt_adherence) AS avg_prompt_adherence
                   FROM telemetry_runs r
                   JOIN telemetry_scores s ON r.id = s.run_id
                   GROUP BY r.agent_id
                   ORDER BY avg_overall DESC"""
            ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 10: Run all telemetry tests**

```
pytest tests/test_telemetry.py -v
```
Expected: all 6 tests `PASSED`.

- [ ] **Step 11: Commit**

```bash
git add src/opencobalt/core/telemetry.py tests/test_telemetry.py
git commit -m "feat(phase15): TelemetryStore schema and CRUD"
```

---

### Task 2: TelemetrySession — record_* methods

**Files:**
- Modify: `src/opencobalt/core/telemetry.py`
- Modify: `tests/test_telemetry.py`

- [ ] **Step 1: Write failing tests for TelemetrySession**

```python
def test_session_record_tool_use(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="route", seed_prompt="x", agent_id="claude-code")
    session.record_tool_use("pytest", success=True, latency_ms=200)
    events = store.list_events(session.run_id)
    assert events[0]["event_type"] == "tool_use"
    assert json.loads(events[0]["payload_json"])["tool"] == "pytest"


def test_session_record_output_sets_raw(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="route", seed_prompt="x", agent_id="claude-code")
    session.record_output("the result", token_count=42)
    run = store.get_run(session.run_id)
    assert run["raw_output"] == "the result"
    assert run["token_count_out"] == 42


def test_session_finish_delegates(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="route", seed_prompt="x", agent_id="claude-code")
    session.finish("complete")
    run = store.get_run(session.run_id)
    assert run["status"] == "complete"
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/test_telemetry.py::test_session_record_tool_use -v
```
Expected: `FAILED` — `AttributeError: 'TelemetrySession' object has no attribute 'record_tool_use'`.

- [ ] **Step 3: Add `TelemetrySession` class to `telemetry.py`**

Add this class **above** `TelemetryStore`:

```python
class TelemetrySession:
    """Thin event accumulator attached to one telemetry run."""

    def __init__(self, run_id: str, store: "TelemetryStore") -> None:
        self.run_id = run_id
        self._store = store

    def record_tool_use(self, tool_name: str, *, success: bool = True, latency_ms: int = 0) -> None:
        self._store.add_event(self.run_id, "tool_use", {"tool": tool_name, "success": success, "latency_ms": latency_ms})

    def record_artifact(self, artifact_type: str, artifact_id: str) -> None:
        self._store.add_event(self.run_id, "artifact", {"type": artifact_type, "id": artifact_id})

    def record_retry(self, reason: str = "") -> None:
        self._store.add_event(self.run_id, "retry", {"reason": reason})

    def record_output(self, output: str, token_count: int | None = None) -> None:
        self._store.add_event(self.run_id, "output", {"length": len(output), "token_count": token_count})
        self._store.set_raw_output(self.run_id, output, token_count_out=token_count)

    def record_agent_switch(self, from_agent: str, to_agent: str) -> None:
        self._store.add_event(self.run_id, "agent_switch", {"from": from_agent, "to": to_agent})

    def record_skill_use(self, skill_id: str) -> None:
        self._store.add_event(self.run_id, "skill_use", {"skill_id": skill_id})

    def record_connector_use(self, connector_id: str) -> None:
        self._store.add_event(self.run_id, "connector_use", {"connector_id": connector_id})

    def record_gate_pass(self, gate_name: str = "") -> None:
        self._store.add_event(self.run_id, "gate_pass", {"gate": gate_name})

    def record_gate_fail(self, gate_name: str = "", reason: str = "") -> None:
        self._store.add_event(self.run_id, "gate_fail", {"gate": gate_name, "reason": reason})

    def finish(self, status: str = "complete") -> None:
        self._store.finish_run(self.run_id, status)
```

- [ ] **Step 4: Run all telemetry tests**

```
pytest tests/test_telemetry.py -v
```
Expected: all 9 tests `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add src/opencobalt/core/telemetry.py tests/test_telemetry.py
git commit -m "feat(phase15): TelemetrySession record_* methods"
```

---

### Task 3: OllamaJudge — prompt, parse, fallback

**Files:**
- Create: `src/opencobalt/core/ollama_judge.py`
- Create: `tests/test_ollama_judge.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_ollama_judge.py
import json
from unittest.mock import patch
from opencobalt.core.ollama_judge import OllamaJudge, _QUALITATIVE_KEYS


def test_judge_returns_all_keys_on_good_response():
    good_json = json.dumps({
        "output_quality": 85, "prompt_adherence": 90, "novel_ideation": 60,
        "context_handling": 70, "tool_appropriateness": 75, "task_decomposition": 65,
        "agent_selection": 80, "reasoning": "Solid.", "summary": "Did the thing.",
    })
    judge = OllamaJudge(model="llama3")
    with patch.object(judge, "_call_ollama", return_value=good_json):
        result = judge.judge(prompt="summarize logs", output="log summary here", heuristics={})
    for key in _QUALITATIVE_KEYS:
        assert key in result
        assert isinstance(result[key], int)
        assert 1 <= result[key] <= 100
    assert result["reasoning"] == "Solid."
    assert result["summary"] == "Did the thing."
    assert result["_judge"] == "ollama:llama3"


def test_judge_falls_back_on_bad_json():
    judge = OllamaJudge(model="llama3")
    with patch.object(judge, "_call_ollama", return_value="not json at all"):
        result = judge.judge(prompt="x", output="y", heuristics={})
    for key in _QUALITATIVE_KEYS:
        assert result[key] == 50
    assert result["_judge"] == "heuristic"


def test_judge_falls_back_when_ollama_unavailable():
    judge = OllamaJudge(model="llama3")
    with patch.object(judge, "_call_ollama", return_value=None):
        result = judge.judge(prompt="x", output="y", heuristics={})
    assert result["_judge"] == "heuristic"


def test_output_truncated_to_4000_chars():
    captured = {}
    def fake_call(prompt: str) -> str:
        captured["prompt"] = prompt
        return None
    judge = OllamaJudge()
    with patch.object(judge, "_call_ollama", side_effect=fake_call):
        judge.judge(prompt="p", output="x" * 5000, heuristics={})
    assert "x" * 4000 in captured["prompt"]
    assert "x" * 4001 not in captured["prompt"]


def test_judge_name_property():
    assert OllamaJudge(model="mistral").judge_name == "ollama:mistral"
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/test_ollama_judge.py -v
```
Expected: `FAILED` — `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/opencobalt/core/ollama_judge.py`**

```python
"""Ollama-backed judge for multi-dimensional run scoring."""
from __future__ import annotations

import json
import re
import subprocess

_QUALITATIVE_KEYS = [
    "output_quality",
    "prompt_adherence",
    "novel_ideation",
    "context_handling",
    "tool_appropriateness",
    "task_decomposition",
    "agent_selection",
]

_FALLBACK = 50

_PROMPT_TEMPLATE = """\
You are a precise AI output evaluator. Score the following AI task run.

## Original Prompt
{prompt}

## Output
{output}

## Heuristic Signals
{heuristics}

## Instructions
Return ONLY valid JSON with these exact keys. Each value is an integer 1-100.
"reasoning" is a 2-3 sentence explanation of the overall score.
"summary" is a 2-3 sentence description of what was done and the result.

{{
  "output_quality": <int>,
  "prompt_adherence": <int>,
  "novel_ideation": <int>,
  "context_handling": <int>,
  "tool_appropriateness": <int>,
  "task_decomposition": <int>,
  "agent_selection": <int>,
  "reasoning": "<string>",
  "summary": "<string>"
}}

Score strictly. 50 = average. 80+ = genuinely good. 95+ = exceptional.\
"""

_MAX_OUTPUT_CHARS = 4000


class OllamaJudge:
    def __init__(self, model: str = "llama3") -> None:
        self.model = model

    @property
    def judge_name(self) -> str:
        return f"ollama:{self.model}"

    def judge(self, *, prompt: str, output: str, heuristics: dict) -> dict:
        truncated = output[:_MAX_OUTPUT_CHARS]
        scoring_prompt = _PROMPT_TEMPLATE.format(
            prompt=prompt,
            output=truncated,
            heuristics=json.dumps(heuristics, indent=2),
        )
        raw = self._call_ollama(scoring_prompt)
        if raw is None:
            return self._fallback()
        return self._parse(raw)

    def _call_ollama(self, prompt: str) -> str | None:
        try:
            result = subprocess.run(
                ["ollama", "run", self.model, prompt],
                capture_output=True,
                text=True,
                timeout=120,
            )
            return result.stdout if result.returncode == 0 else None
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    def _parse(self, raw: str) -> dict:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return self._fallback()
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            return self._fallback()

        result: dict = {}
        for key in _QUALITATIVE_KEYS:
            val = data.get(key, _FALLBACK)
            result[key] = int(val) if isinstance(val, (int, float)) else _FALLBACK

        result["reasoning"] = str(data.get("reasoning", ""))
        result["summary"] = str(data.get("summary", ""))
        result["_judge"] = self.judge_name
        return result

    def _fallback(self) -> dict:
        result = {key: _FALLBACK for key in _QUALITATIVE_KEYS}
        result["reasoning"] = ""
        result["summary"] = ""
        result["_judge"] = "heuristic"
        return result
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_ollama_judge.py -v
```
Expected: all 5 tests `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add src/opencobalt/core/ollama_judge.py tests/test_ollama_judge.py
git commit -m "feat(phase15): OllamaJudge prompt, parse, fallback"
```

---

### Task 4: ScoringEngine — heuristics and full score assembly

**Files:**
- Create: `src/opencobalt/core/scoring_engine.py`
- Create: `tests/test_scoring_engine.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_scoring_engine.py
import json
from unittest.mock import MagicMock
from opencobalt.core.telemetry import TelemetryStore
from opencobalt.core.scoring_engine import ScoringEngine
from opencobalt.core.ollama_judge import OllamaJudge


def _make_store(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="route", seed_prompt="build auth module", agent_id="claude-code")
    session.record_tool_use("pytest")
    session.record_tool_use("git")
    session.record_artifact("code", "art-1")
    session.record_retry("gate failed")
    session.record_output("auth module built", token_count=500)
    session.record_gate_pass("tests")
    session.finish("complete")
    return store, session.run_id


def test_score_produces_all_categories(tmp_path):
    store, run_id = _make_store(tmp_path)
    judge = MagicMock(spec=OllamaJudge)
    judge.judge_name = "ollama:llama3"
    judge.judge.return_value = {
        "output_quality": 80, "prompt_adherence": 85, "novel_ideation": 55,
        "context_handling": 70, "tool_appropriateness": 75, "task_decomposition": 65,
        "agent_selection": 72, "reasoning": "Good work.", "summary": "Built auth.",
        "_judge": "ollama:llama3",
    }
    engine = ScoringEngine(store, judge=judge)
    score = engine.score(run_id)
    assert score["run_id"] == run_id
    assert 1 <= score["overall"] <= 100
    assert score["token_efficiency"] is not None
    assert score["latency_score"] is not None
    assert score["convergence_quality"] is not None
    result = store.get_score(run_id)
    assert result is not None
    assert result["overall"] == score["overall"]


def test_overall_weighted_correctly(tmp_path):
    store, run_id = _make_store(tmp_path)
    judge = MagicMock(spec=OllamaJudge)
    judge.judge_name = "ollama:llama3"
    judge.judge.return_value = {
        "output_quality": 100, "prompt_adherence": 100, "novel_ideation": 100,
        "context_handling": 100, "tool_appropriateness": 100, "task_decomposition": 100,
        "agent_selection": 100, "reasoning": "", "summary": "", "_judge": "ollama:llama3",
    }
    engine = ScoringEngine(store, judge=judge)
    score = engine.score(run_id)
    assert score["overall"] >= 90


def test_fallback_judge_produces_valid_score(tmp_path):
    store, run_id = _make_store(tmp_path)
    judge = MagicMock(spec=OllamaJudge)
    judge.judge_name = "heuristic"
    judge.judge.return_value = {
        "output_quality": 50, "prompt_adherence": 50, "novel_ideation": 50,
        "context_handling": 50, "tool_appropriateness": 50, "task_decomposition": 50,
        "agent_selection": 50, "reasoning": "", "summary": "", "_judge": "heuristic",
    }
    engine = ScoringEngine(store, judge=judge)
    score = engine.score(run_id)
    assert score["judge"] == "heuristic"
    assert 1 <= score["overall"] <= 100


def test_summary_saved_to_run(tmp_path):
    store, run_id = _make_store(tmp_path)
    judge = MagicMock(spec=OllamaJudge)
    judge.judge_name = "ollama:llama3"
    judge.judge.return_value = {
        **{k: 70 for k in ["output_quality","prompt_adherence","novel_ideation",
                            "context_handling","tool_appropriateness","task_decomposition","agent_selection"]},
        "reasoning": "r", "summary": "Built the auth module successfully.", "_judge": "ollama:llama3",
    }
    engine = ScoringEngine(store, judge=judge)
    engine.score(run_id)
    run = store.get_run(run_id)
    assert run["summary"] == "Built the auth module successfully."
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/test_scoring_engine.py -v
```
Expected: `FAILED` — `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/opencobalt/core/scoring_engine.py`**

```python
"""Multi-dimensional run scorer using OllamaJudge + heuristics."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .ollama_judge import OllamaJudge
from .telemetry import TelemetryStore

_WEIGHTS = {
    "output_quality": 0.25,
    "prompt_adherence": 0.15,
    "token_efficiency": 0.12,
    "tool_appropriateness": 0.10,
    "novel_ideation": 0.10,
    "context_handling": 0.08,
    "latency_score": 0.08,
    "task_decomposition": 0.06,
    "agent_selection": 0.05,
    "convergence_quality": 0.01,
}


class ScoringEngine:
    def __init__(self, store: TelemetryStore, judge: OllamaJudge | None = None) -> None:
        self._store = store
        self._judge = judge or OllamaJudge()

    def score(self, run_id: str) -> dict:
        run = self._store.get_run(run_id)
        if run is None:
            raise ValueError(f"Unknown run: {run_id}")

        events = self._store.list_events(run_id)
        heuristics = self._compute_heuristics(run, events)

        qualitative = self._judge.judge(
            prompt=run["seed_prompt"],
            output=run.get("raw_output") or "",
            heuristics=heuristics,
        )

        token_efficiency = _score_token_efficiency(heuristics)
        latency_score = _score_latency(heuristics)
        convergence_quality = _score_convergence(heuristics)

        all_scores = {
            **{k: qualitative.get(k, 50) for k in _WEIGHTS if k not in
               ("token_efficiency", "latency_score", "convergence_quality")},
            "token_efficiency": token_efficiency,
            "latency_score": latency_score,
            "convergence_quality": convergence_quality,
        }
        overall = round(sum(all_scores[cat] * w for cat, w in _WEIGHTS.items()))

        judge_label = qualitative.get("_judge", self._judge.judge_name)

        score = {
            "run_id": run_id,
            "scored_at": datetime.now(tz=timezone.utc).isoformat(),
            "judge": judge_label,
            "overall": overall,
            **all_scores,
            "judge_reasoning": qualitative.get("reasoning", ""),
            "heuristics": heuristics,
        }

        self._store.save_score(score)

        if summary := qualitative.get("summary"):
            self._store.set_summary(run_id, summary)

        return score

    def _compute_heuristics(self, run: dict, events: list[dict]) -> dict:
        def _payloads(etype: str) -> list[dict]:
            return [json.loads(e["payload_json"]) for e in events if e["event_type"] == etype]

        tool_events = _payloads("tool_use")
        retry_events = _payloads("retry")
        gate_pass = [e for e in events if e["event_type"] == "gate_pass"]
        gate_fail = [e for e in events if e["event_type"] == "gate_fail"]

        distinct_tools = len({p.get("tool", "") for p in tool_events} - {""})
        total_gates = len(gate_pass) + len(gate_fail)
        gate_pass_rate = len(gate_pass) / total_gates if total_gates > 0 else 1.0

        token_in = run.get("token_count_in") or 0
        token_out = run.get("token_count_out") or 0
        if token_out > 0 and token_in > 0:
            token_ratio = token_out / token_in
        else:
            raw_out = run.get("raw_output") or ""
            seed = run.get("seed_prompt") or ""
            token_ratio = len(raw_out) / max(len(seed), 1)

        return {
            "token_count_in": token_in,
            "token_count_out": token_out,
            "token_ratio": round(token_ratio, 2),
            "distinct_tool_count": distinct_tools,
            "retry_count": len(retry_events),
            "latency_ms": run.get("latency_ms") or 0,
            "gate_pass_rate": round(gate_pass_rate, 2),
            "total_gates": total_gates,
            "artifacts_produced": run.get("artifacts_produced") or 0,
        }


def _score_token_efficiency(h: dict) -> int:
    ratio = h["token_ratio"]
    if ratio >= 5:
        return 90
    if ratio >= 3:
        return 75
    if ratio >= 1.5:
        return 60
    if ratio >= 0.5:
        return 45
    return 30


def _score_latency(h: dict) -> int:
    ms = h["latency_ms"]
    if ms == 0:
        return 70
    if ms < 5_000:
        return 95
    if ms < 15_000:
        return 85
    if ms < 30_000:
        return 75
    if ms < 60_000:
        return 65
    if ms < 120_000:
        return 55
    return 40


def _score_convergence(h: dict) -> int:
    base = int(h["gate_pass_rate"] * 80) + 20
    penalty = min(h["retry_count"] * 5, 30)
    return max(base - penalty, 1)
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_scoring_engine.py -v
```
Expected: all 4 tests `PASSED`.

- [ ] **Step 5: Run full suite to check for regressions**

```
python3 -m pytest -q
```
Expected: all existing tests still `PASSED`, 4 new tests added.

- [ ] **Step 6: Commit**

```bash
git add src/opencobalt/core/scoring_engine.py src/opencobalt/core/ollama_judge.py tests/test_scoring_engine.py
git commit -m "feat(phase15): ScoringEngine with heuristics and weighted overall"
```

---

### Task 5: MarkdownExporter — file render and related links

**Files:**
- Create: `src/opencobalt/core/markdown_exporter.py`
- Create: `tests/test_markdown_exporter.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_markdown_exporter.py
import json
from pathlib import Path
from opencobalt.core.markdown_exporter import MarkdownExporter


def _run(run_id: str = "abc12345-0000-0000-0000-000000000000") -> dict:
    return {
        "id": run_id,
        "run_type": "route",
        "seed_prompt": "summarize logs",
        "agent_id": "claude-code",
        "model_used": "claude-sonnet-4-6",
        "started_at": 1749340800.0,
        "latency_ms": 3200,
        "retry_count": 0,
        "artifacts_produced": 1,
        "token_count_in": 200,
        "token_count_out": 800,
        "summary": "Summarized the log file.",
        "tool_calls_json": '["pytest", "git"]',
        "skills_used_json": '["tdd"]',
        "connectors_used_json": '[]',
    }


def _score(run_id: str = "abc12345-0000-0000-0000-000000000000") -> dict:
    return {
        "overall": 78, "judge": "ollama:llama3",
        "output_quality": 80, "prompt_adherence": 85, "novel_ideation": 55,
        "context_handling": 70, "token_efficiency": 75, "latency_score": 90,
        "tool_appropriateness": 72, "task_decomposition": 65, "agent_selection": 70,
        "convergence_quality": 95, "judge_reasoning": "Solid output.",
    }


def test_export_creates_file(tmp_path):
    exporter = MarkdownExporter()
    path = exporter.export_run(_run(), _score(), tmp_path)
    assert path.exists()
    assert path.suffix == ".md"


def test_filename_contains_run_type_and_id(tmp_path):
    exporter = MarkdownExporter()
    path = exporter.export_run(_run(), _score(), tmp_path)
    assert "route" in path.stem
    assert "abc12345" in path.stem


def test_frontmatter_keys_present(tmp_path):
    exporter = MarkdownExporter()
    path = exporter.export_run(_run(), _score(), tmp_path)
    content = path.read_text()
    assert "overall_score: 78" in content
    assert "agent: claude-code" in content
    assert "run_type: route" in content


def test_score_table_present(tmp_path):
    exporter = MarkdownExporter()
    path = exporter.export_run(_run(), _score(), tmp_path)
    content = path.read_text()
    assert "| Output Quality |" in content
    assert "| 80 |" in content


def test_related_links_populated(tmp_path):
    exporter = MarkdownExporter()
    run1_id = "aaaaaaaa-0000-0000-0000-000000000000"
    run2_id = "bbbbbbbb-0000-0000-0000-000000000000"
    # Write two older files first
    path1 = exporter.export_run({**_run(run1_id), "started_at": 1749340700.0}, _score(run1_id), tmp_path)
    path2 = exporter.export_run({**_run(run2_id), "started_at": 1749340750.0}, _score(run2_id), tmp_path)
    # Now write a third -- should reference the two above
    path3 = exporter.export_run({**_run(), "started_at": 1749340800.0}, _score(), tmp_path)
    content = path3.read_text()
    assert path1.stem in content or path2.stem in content
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/test_markdown_exporter.py -v
```
Expected: `FAILED` — `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/opencobalt/core/markdown_exporter.py`**

```python
"""Optional markdown export for scored telemetry runs."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path


class MarkdownExporter:
    def export_run(self, run: dict, score: dict, output_dir: Path) -> Path:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        dt = datetime.fromtimestamp(run["started_at"], tz=timezone.utc)
        timestamp_str = dt.strftime("%Y-%m-%d_%H%M%S")
        run_type = run["run_type"]
        run_id_short = run["id"][:8]
        filename = f"{timestamp_str}_{run_type}_{run_id_short}.md"
        filepath = output_dir / filename

        related = self._find_related(run_type, filepath.stem, output_dir)
        content = self._render(run, score, related)
        filepath.write_text(content, encoding="utf-8")
        return filepath

    def _find_related(self, run_type: str, current_stem: str, output_dir: Path) -> list[str]:
        pattern = re.compile(
            rf"\d{{4}}-\d{{2}}-\d{{2}}_\d{{6}}_{re.escape(run_type)}_[0-9a-f]{{8}}"
        )
        candidates = [
            f.stem
            for f in sorted(output_dir.glob(f"*_{run_type}_*.md"), reverse=True)
            if f.stem != current_stem and pattern.match(f.stem)
        ]
        return candidates[:3]

    def _render(self, run: dict, score: dict, related: list[str]) -> str:
        tool_calls = json.loads(run.get("tool_calls_json") or "[]")
        skills = json.loads(run.get("skills_used_json") or "[]")
        connectors = json.loads(run.get("connectors_used_json") or "[]")
        latency_s = f"{run['latency_ms'] // 1000}s" if run.get("latency_ms") else "unknown"
        related_links = ", ".join(f"[[{r}]]" for r in related)

        lines = [
            "---",
            f"id: {run['id']}",
            f"date: {_iso(run['started_at'])}",
            f"run_type: {run['run_type']}",
            f"agent: {run['agent_id']}",
            f"model: {run.get('model_used', '')}",
            f"overall_score: {score['overall']}",
            f"tags: [{run['run_type']}, {run['agent_id']}]",
        ]
        if related_links:
            lines.append(f"related: {related_links}")
        lines += [
            "---",
            "",
            f"# Run: {run['seed_prompt']}",
            "",
            f"**Score:** {score['overall']}/100 | **Judge:** {score['judge']}",
            "",
            "## Summary",
            "",
            run.get("summary") or "_No summary available._",
            "",
            "## Scores",
            "",
            "| Category | Score |",
            "|---|---|",
            f"| Output Quality | {score.get('output_quality', '-')} |",
            f"| Prompt Adherence | {score.get('prompt_adherence', '-')} |",
            f"| Novel Ideation | {score.get('novel_ideation', '-')} |",
            f"| Context Handling | {score.get('context_handling', '-')} |",
            f"| Tool Appropriateness | {score.get('tool_appropriateness', '-')} |",
            f"| Token Efficiency | {score.get('token_efficiency', '-')} |",
            f"| Latency | {score.get('latency_score', '-')} |",
            f"| Task Decomposition | {score.get('task_decomposition', '-')} |",
            f"| Agent Selection | {score.get('agent_selection', '-')} |",
            f"| Convergence Quality | {score.get('convergence_quality', '-')} |",
            "",
        ]
        if score.get("judge_reasoning"):
            lines += ["## Reasoning", "", score["judge_reasoning"], ""]
        lines += [
            "## Run Details",
            "",
            f"- **Tools used:** {', '.join(tool_calls) or 'none'}",
            f"- **Skills used:** {', '.join(skills) or 'none'}",
            f"- **Connectors used:** {', '.join(connectors) or 'none'}",
            f"- **Retries:** {run.get('retry_count', 0)} | **Latency:** {latency_s}",
            f"- **Tokens:** {run.get('token_count_in') or '?'} in / {run.get('token_count_out') or '?'} out",
            "",
        ]
        return "\n".join(lines)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_markdown_exporter.py -v
```
Expected: all 5 tests `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add src/opencobalt/core/markdown_exporter.py tests/test_markdown_exporter.py
git commit -m "feat(phase15): MarkdownExporter with related links"
```

---

### Task 6: CLI — telemetry command group

**Files:**
- Modify: `src/opencobalt/cli.py`

- [ ] **Step 1: Write failing CLI tests**

```python
# tests/test_cli_telemetry.py
import json
from typer.testing import CliRunner
from opencobalt.cli import app
from opencobalt.core.telemetry import TelemetryStore
from opencobalt.core.scoring_engine import ScoringEngine
from unittest.mock import patch, MagicMock


runner = CliRunner()


def _seed_db(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.db")
    session = store.start_run(run_type="route", seed_prompt="summarize logs", agent_id="claude-code")
    session.record_tool_use("pytest")
    session.record_output("log summary", token_count=100)
    session.finish("complete")
    judge = MagicMock()
    judge.judge_name = "heuristic"
    judge.judge.return_value = {k: 70 for k in [
        "output_quality","prompt_adherence","novel_ideation",
        "context_handling","tool_appropriateness","task_decomposition","agent_selection",
    ]}
    judge.judge.return_value.update({"reasoning": "", "summary": "Done.", "_judge": "heuristic"})
    ScoringEngine(store, judge=judge).score(session.run_id)
    return store, session.run_id


def test_telemetry_status(tmp_path, monkeypatch):
    store, _ = _seed_db(tmp_path)
    monkeypatch.setattr("opencobalt.cli._TELEMETRY_DB_PATH", tmp_path / "telemetry.db")
    result = runner.invoke(app, ["telemetry", "status"])
    assert result.exit_code == 0
    assert "1" in result.output  # 1 run


def test_telemetry_runs(tmp_path, monkeypatch):
    store, run_id = _seed_db(tmp_path)
    monkeypatch.setattr("opencobalt.cli._TELEMETRY_DB_PATH", tmp_path / "telemetry.db")
    result = runner.invoke(app, ["telemetry", "runs"])
    assert result.exit_code == 0
    assert run_id[:8] in result.output


def test_telemetry_show(tmp_path, monkeypatch):
    store, run_id = _seed_db(tmp_path)
    monkeypatch.setattr("opencobalt.cli._TELEMETRY_DB_PATH", tmp_path / "telemetry.db")
    result = runner.invoke(app, ["telemetry", "show", run_id])
    assert result.exit_code == 0
    assert "summarize logs" in result.output


def test_telemetry_scores(tmp_path, monkeypatch):
    store, _ = _seed_db(tmp_path)
    monkeypatch.setattr("opencobalt.cli._TELEMETRY_DB_PATH", tmp_path / "telemetry.db")
    result = runner.invoke(app, ["telemetry", "scores"])
    assert result.exit_code == 0
    assert "claude-code" in result.output
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/test_cli_telemetry.py -v
```
Expected: `FAILED`.

- [ ] **Step 3: Add telemetry app and constant to `cli.py`**

Find the block near line 88–103 where other sub-apps are registered (e.g. `benchmark_app`). Add:

```python
# After: benchmark_app = typer.Typer(...)
telemetry_app = typer.Typer(help="Telemetry commands.", invoke_without_command=True)
app.add_typer(telemetry_app, name="telemetry")
```

After `_DB_PATH = Path(".opencobalt") / "ledger.db"` add:

```python
_TELEMETRY_DB_PATH = Path(".opencobalt") / "telemetry.db"
```

- [ ] **Step 4: Add telemetry commands to `cli.py`**

Add these commands near the end of the file, before `session_start`:

```python
@telemetry_app.callback(invoke_without_command=True)
def telemetry(ctx: typer.Context) -> None:
    """Telemetry capture, scoring, and export."""
    if ctx.invoked_subcommand is None:
        console.print("[dim]Use: opencobalt telemetry <subcommand>[/dim]")
        console.print("[dim]Subcommands: status, show, runs, scores, score, export[/dim]")


@telemetry_app.command("status")
def telemetry_status() -> None:
    """Summary of scored runs and top agent."""
    from .core.telemetry import TelemetryStore

    store = TelemetryStore(_TELEMETRY_DB_PATH)
    runs = store.list_runs(limit=1000)
    scored = [r for r in runs if r["status"] == "scored"]
    last_day = [r for r in runs if r.get("started_at", 0) > (time.time() - 86400)]
    ollama_count = 0
    heuristic_count = 0
    for r in scored:
        s = store.get_score(r["id"])
        if s and s["judge"].startswith("ollama"):
            ollama_count += 1
        elif s:
            heuristic_count += 1

    console.print(f"\n  [bold {_COBALT}]Telemetry Status[/bold {_COBALT}]\n")
    console.print(f"  Total runs:     {len(runs)}")
    console.print(f"  Scored runs:    {len(scored)}")
    console.print(f"  Last 24h:       {len(last_day)}")
    console.print(f"  Ollama-scored:  {ollama_count}")
    console.print(f"  Heuristic-only: {heuristic_count}")

    board = store.get_leaderboard()
    if board:
        top = board[0]
        console.print(f"  Top agent:      {top['agent_id']} (avg {top['avg_overall']:.0f})\n")
    else:
        console.print()


@telemetry_app.command("runs")
def telemetry_runs(
    limit: int = typer.Option(20, "--limit", "-n"),
    agent: str = typer.Option(None, "--agent", "-a"),
    run_type: str = typer.Option(None, "--type", "-t"),
) -> None:
    """List recent telemetry runs with their scores."""
    from .core.telemetry import TelemetryStore

    store = TelemetryStore(_TELEMETRY_DB_PATH)
    runs = store.list_runs(limit=limit, agent_id=agent, run_type=run_type)

    console.print(f"\n  [bold {_COBALT}]Recent Runs[/bold {_COBALT}]\n")
    if not runs:
        console.print("  [dim]No runs recorded yet.[/dim]\n")
        return

    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("ID", style="dim")
    table.add_column("Type")
    table.add_column("Agent", style=f"{_COBALT}")
    table.add_column("Prompt")
    table.add_column("Score", justify="right")
    table.add_column("Status", style="dim")

    for r in runs:
        score_row = store.get_score(r["id"])
        score_str = str(score_row["overall"]) if score_row else "-"
        prompt_short = r["seed_prompt"][:40] + "..." if len(r["seed_prompt"]) > 40 else r["seed_prompt"]
        table.add_row(r["id"][:8], r["run_type"], r["agent_id"], prompt_short, score_str, r["status"])

    console.print(table)


@telemetry_app.command("show")
def telemetry_show(run_id: str = typer.Argument(...)) -> None:
    """Full breakdown for one run."""
    from .core.telemetry import TelemetryStore

    store = TelemetryStore(_TELEMETRY_DB_PATH)
    run = store.get_run(run_id)
    if run is None:
        console.print(f"[red]Run not found: {run_id}[/red]")
        raise typer.Exit(1)

    score = store.get_score(run_id)
    console.print(f"\n  [bold {_COBALT}]Run: {run['seed_prompt']}[/bold {_COBALT}]\n")
    console.print(f"  ID:      {run['id']}")
    console.print(f"  Type:    {run['run_type']}")
    console.print(f"  Agent:   {run['agent_id']}")
    console.print(f"  Status:  {run['status']}")
    if run.get("summary"):
        console.print(f"\n  {run['summary']}")

    if score:
        console.print(f"\n  [bold]Overall Score: {score['overall']}/100[/bold] ({score['judge']})\n")
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        for cat, label in [
            ("output_quality", "Output Quality"),
            ("prompt_adherence", "Prompt Adherence"),
            ("novel_ideation", "Novel Ideation"),
            ("context_handling", "Context Handling"),
            ("tool_appropriateness", "Tool Appropriateness"),
            ("token_efficiency", "Token Efficiency"),
            ("latency_score", "Latency"),
            ("task_decomposition", "Task Decomposition"),
            ("agent_selection", "Agent Selection"),
            ("convergence_quality", "Convergence Quality"),
        ]:
            val = score.get(cat)
            table.add_row(label, str(val) if val is not None else "-")
        console.print(table)
        if score.get("judge_reasoning"):
            console.print(f"\n  [dim]{score['judge_reasoning']}[/dim]")
    console.print()


@telemetry_app.command("scores")
def telemetry_scores() -> None:
    """Agent leaderboard by category."""
    from .core.telemetry import TelemetryStore

    store = TelemetryStore(_TELEMETRY_DB_PATH)
    board = store.get_leaderboard()

    console.print(f"\n  [bold {_COBALT}]Telemetry Leaderboard[/bold {_COBALT}]\n")
    if not board:
        console.print("  [dim]No scored runs yet.[/dim]\n")
        return

    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Agent", style=f"{_COBALT}")
    table.add_column("Runs", justify="right", style="dim")
    table.add_column("Overall", justify="right")
    table.add_column("Quality", justify="right", style="dim")
    table.add_column("Adherence", justify="right", style="dim")
    table.add_column("Efficiency", justify="right", style="dim")

    for entry in board:
        table.add_row(
            entry["agent_id"],
            str(entry["total"]),
            f"{entry['avg_overall']:.0f}",
            f"{entry.get('avg_output_quality') or 0:.0f}",
            f"{entry.get('avg_prompt_adherence') or 0:.0f}",
            f"{entry.get('avg_token_efficiency') or 0:.0f}",
        )
    console.print(table)
    console.print()


@telemetry_app.command("score")
def telemetry_score_run(run_id: str = typer.Argument(...)) -> None:
    """Score or rescore a run."""
    from .core.ollama_judge import OllamaJudge
    from .core.scoring_engine import ScoringEngine
    from .core.telemetry import TelemetryStore

    store = TelemetryStore(_TELEMETRY_DB_PATH)
    run = store.get_run(run_id)
    if run is None:
        console.print(f"[red]Run not found: {run_id}[/red]")
        raise typer.Exit(1)

    from .core.config import Config
    model = Config().get("ollama_judge_model") or "llama3"
    judge = OllamaJudge(model=model)
    with console.status("[dim]Scoring...[/dim]", spinner="dots"):
        result = ScoringEngine(store, judge=judge).score(run_id)
    console.print(f"  Overall: {result['overall']}/100 ({result['judge']})\n")


@telemetry_app.command("export")
def telemetry_export(
    output: str = typer.Option(None, "--output", "-o", help="Directory to write .md files"),
) -> None:
    """Export scored runs to markdown files."""
    from pathlib import Path as _Path

    from .core.config import Config
    from .core.markdown_exporter import MarkdownExporter
    from .core.telemetry import TelemetryStore

    store = TelemetryStore(_TELEMETRY_DB_PATH)
    export_dir = _Path(output) if output else None
    if export_dir is None:
        cfg = Config()
        export_dir_str = cfg.get("telemetry_export_path")
        if not export_dir_str:
            console.print("[red]No export path configured.[/red]")
            console.print("[dim]Set one with: opencobalt config set telemetry_export_path <dir>[/dim]")
            raise typer.Exit(1)
        export_dir = _Path(export_dir_str)

    runs = store.list_runs(limit=10000)
    exporter = MarkdownExporter()
    count = 0
    for r in runs:
        score = store.get_score(r["id"])
        if score is None:
            continue
        exporter.export_run(r, score, export_dir)
        count += 1

    console.print(f"  Exported {count} run(s) to {export_dir}\n")
```

- [ ] **Step 5: Run telemetry CLI tests**

```
pytest tests/test_cli_telemetry.py -v
```
Expected: all 4 tests `PASSED`.

- [ ] **Step 6: Run full suite**

```
python3 -m pytest -q
```
Expected: all previous tests still passing.

- [ ] **Step 7: Commit**

```bash
git add src/opencobalt/cli.py tests/test_cli_telemetry.py
git commit -m "feat(phase15): telemetry CLI command group (status, runs, show, scores, score, export)"
```

---

### Task 7: Overlay integration — session creation and scoring

**Files:**
- Modify: `src/opencobalt/core/overlay.py`
- Modify: `tests/test_overlay.py` (or create if it doesn't exist)

- [ ] **Step 1: Write failing integration test**

```python
# Add to tests/test_overlay.py (or create it)
from unittest.mock import MagicMock, patch
from pathlib import Path
from opencobalt.core.overlay import OverlayController
from opencobalt.core.telemetry import TelemetryStore


def test_handle_prompt_creates_telemetry_run(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.db")
    mock_score = MagicMock(return_value={"overall": 70, "judge": "heuristic"})

    with patch("opencobalt.core.overlay._get_telemetry_store", return_value=store), \
         patch("opencobalt.core.overlay._score_run", mock_score):
        controller = OverlayController(
            route_runner=lambda p: None,
            convergence_runner=lambda p: MagicMock(id="sess-1", status="converged"),
        )
        controller.handle_prompt("summarize this log")

    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0]["seed_prompt"] == "summarize this log"
    assert runs[0]["status"] in ("complete", "scored", "failed")
```

- [ ] **Step 2: Run test to confirm it fails**

```
pytest tests/test_overlay.py::test_handle_prompt_creates_telemetry_run -v
```
Expected: `FAILED`.

- [ ] **Step 3: Add telemetry wiring to `overlay.py`**

At the top of `overlay.py`, add imports:

```python
from pathlib import Path as _Path
```

After the existing imports block, add these two module-level helpers:

```python
def _get_telemetry_store():
    from .telemetry import TelemetryStore
    return TelemetryStore(_Path(".opencobalt") / "telemetry.db")


def _score_run(store, run_id: str) -> dict:
    from .config import Config
    from .ollama_judge import OllamaJudge
    from .scoring_engine import ScoringEngine
    model = Config().get("ollama_judge_model") or "llama3"
    return ScoringEngine(store, judge=OllamaJudge(model=model)).score(run_id)
```

Modify `handle_prompt` in `OverlayController` to wrap the run with telemetry:

```python
def handle_prompt(self, text: str) -> OverlayOutcome:
    classification = self.classify(text)
    store = _get_telemetry_store()
    session = store.start_run(
        run_type=classification.mode,
        seed_prompt=text,
        agent_id="overlay",
    )
    try:
        outcome = self._dispatch(classification)
        session.finish("complete")
    except Exception:
        session.finish("failed")
        raise
    finally:
        try:
            _score_run(store, session.run_id)
        except Exception:
            pass
    return outcome
```

Extract the existing `handle_prompt` dispatch body into a new `_dispatch` method. The
current `handle_prompt` (lines 63-73 of `overlay.py`) reads:

```python
def handle_prompt(self, text: str) -> OverlayOutcome:
    classification = self.classify(text)
    if classification.mode == "route":
        return self._handle_route(classification.prompt)
    if classification.mode == "converge":
        return self._handle_converge(classification.prompt)
    if classification.mode == "auto":
        return self._handle_auto(classification)
    if classification.mode == "mission":
        return self._handle_mission(classification)
    raise ValueError(f"unknown overlay mode: {classification.mode}")
```

Replace it with:

```python
def handle_prompt(self, text: str) -> OverlayOutcome:
    classification = self.classify(text)
    store = _get_telemetry_store()
    session = store.start_run(
        run_type=classification.mode,
        seed_prompt=text,
        agent_id="overlay",
    )
    try:
        outcome = self._dispatch(classification)
        session.finish("complete")
    except Exception:
        session.finish("failed")
        raise
    finally:
        try:
            _score_run(store, session.run_id)
        except Exception:
            pass
    return outcome

def _dispatch(self, classification: PromptClassification) -> OverlayOutcome:
    if classification.mode == "route":
        return self._handle_route(classification.prompt)
    if classification.mode == "converge":
        return self._handle_converge(classification.prompt)
    if classification.mode == "auto":
        return self._handle_auto(classification)
    if classification.mode == "mission":
        return self._handle_mission(classification)
    raise ValueError(f"unknown overlay mode: {classification.mode}")
```

- [ ] **Step 4: Run overlay tests**

```
pytest tests/test_overlay.py -v
```
Expected: all overlay tests (including pre-existing ones) `PASSED`.

- [ ] **Step 5: Run full suite**

```
python3 -m pytest -q
```
Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/opencobalt/core/overlay.py tests/test_overlay.py
git commit -m "feat(phase15): overlay creates TelemetrySession and triggers scoring"
```

---

### Task 8: ArtifactBus + ConvergenceChecker one-line integrations

**Files:**
- Modify: `src/opencobalt/core/artifact_bus.py`
- Modify: `src/opencobalt/core/convergence_checker.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_telemetry_integration.py
from unittest.mock import MagicMock
from opencobalt.core.telemetry import TelemetryStore
from opencobalt.core.artifact_bus import AgentArtifact, ArtifactBus, ArtifactType
from opencobalt.core.convergence_checker import ConvergenceChecker
import time, uuid


def test_artifact_bus_records_artifact_event(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="converge", seed_prompt="x", agent_id="claude-code")
    bus = ArtifactBus(tmp_path / "artifacts.db")
    artifact = AgentArtifact(
        id=str(uuid.uuid4()), session_id="sess-1", iteration=0, wave=0,
        producer="claude-code", type=ArtifactType.CODE,
        content="print('hi')", metadata={}, timestamp=time.time(),
    )
    bus.publish(artifact, telemetry_session=session)
    events = store.list_events(session.run_id)
    assert any(e["event_type"] == "artifact" for e in events)


def test_convergence_checker_records_gate_pass(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="converge", seed_prompt="x", agent_id="claude-code")

    tests_gate = MagicMock()
    tests_gate.check.return_value = (True, "")
    checker = ConvergenceChecker(tests_gate=tests_gate)
    checker.check(["tests"], telemetry_session=session)

    events = store.list_events(session.run_id)
    assert any(e["event_type"] == "gate_pass" for e in events)


def test_convergence_checker_records_gate_fail(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="converge", seed_prompt="x", agent_id="claude-code")

    tests_gate = MagicMock()
    tests_gate.check.return_value = (False, "tests failed")
    checker = ConvergenceChecker(tests_gate=tests_gate)
    checker.check(["tests"], telemetry_session=session)

    events = store.list_events(session.run_id)
    assert any(e["event_type"] == "gate_fail" for e in events)
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/test_telemetry_integration.py -v
```
Expected: `FAILED`.

- [ ] **Step 3: Update `ArtifactBus.publish()` in `artifact_bus.py`**

Find the `publish` method signature (currently around line 82). Change it to:

```python
def publish(self, artifact: AgentArtifact, *, telemetry_session=None) -> None:
```

Add one line at the end of the method body (after the existing `conn.execute` insert):

```python
        if telemetry_session is not None:
            telemetry_session.record_artifact(artifact.type, artifact.id)
```

- [ ] **Step 4: Update `ConvergenceChecker.check()` in `convergence_checker.py`**

Find the `check` method signature (line 116). Change it to:

```python
    def check(
        self,
        task_types: list[str],
        task: str = "",
        diff: str = "",
        retry_count: int = 0,
        telemetry_session=None,
    ) -> ConvergenceResult:
```

After the `ok, output = self._tests_gate.check()` block, add:

```python
            if telemetry_session is not None:
                if ok:
                    telemetry_session.record_gate_pass("tests")
                else:
                    telemetry_session.record_gate_fail("tests", output[:200])
```

After the `ok, score, fb = self._verifier_gate.check(task, diff)` block, add:

```python
            if telemetry_session is not None:
                if ok:
                    telemetry_session.record_gate_pass("verifier")
                else:
                    telemetry_session.record_gate_fail("verifier", fb[:200])
```

- [ ] **Step 5: Run integration tests**

```
pytest tests/test_telemetry_integration.py -v
```
Expected: all 3 tests `PASSED`.

- [ ] **Step 6: Run full suite**

```
python3 -m pytest -q
```
Expected: no regressions.

- [ ] **Step 7: Commit**

```bash
git add src/opencobalt/core/artifact_bus.py src/opencobalt/core/convergence_checker.py tests/test_telemetry_integration.py
git commit -m "feat(phase15): ArtifactBus and ConvergenceChecker record telemetry events"
```

---

### Task 9: ConvergenceOrchestrator, AutonomyEngine, MissionPlanner optional session

**Files:**
- Modify: `src/opencobalt/core/convergence_orchestrator.py`
- Modify: `src/opencobalt/core/autonomy_engine.py`
- Modify: `src/opencobalt/core/mission.py`
- Modify: `tests/test_telemetry_integration.py`

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/test_telemetry_integration.py

from opencobalt.core.convergence_orchestrator import ConvergenceOrchestrator
from opencobalt.core.autonomy_engine import AutonomyEngine
from opencobalt.core.mission import MissionPlanner
from opencobalt.core.autonomy_policy import PermissionEnvelope
from opencobalt.core.ledger import Ledger
from unittest.mock import patch


def test_convergence_orchestrator_accepts_session(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="converge", seed_prompt="build auth", agent_id="claude-code")
    ledger = Ledger(tmp_path / "ledger.db")

    checker = MagicMock()
    from opencobalt.core.convergence_checker import ConvergenceResult
    checker.check.return_value = ConvergenceResult(
        passed=True, tests_ok=True, verifier_ok=None,
        verifier_score=None, retry_count=0, feedback="ok",
    )
    with patch("opencobalt.core.convergence_orchestrator.subprocess") as mock_sub, \
         patch("opencobalt.core.convergence_orchestrator.AutoCommitter"):
        mock_sub.run.return_value = MagicMock(returncode=0, stdout="done", stderr="")
        orch = ConvergenceOrchestrator(ledger=ledger, checker=checker)
        # Should accept telemetry_session without error
        orch.run("build auth module", telemetry_session=session)


def test_autonomy_engine_accepts_session(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="auto", seed_prompt="finish app", agent_id="claude-code")
    ledger = Ledger(tmp_path / "ledger.db")
    engine = AutonomyEngine(ledger=ledger)
    run = engine.start("finish app", telemetry_session=session)
    assert run["status"] == "running"


def test_mission_planner_accepts_session(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="mission", seed_prompt="make money", agent_id="claude-code")
    ledger = Ledger(tmp_path / "ledger.db")
    bus = MagicMock()
    planner = MissionPlanner(ledger=ledger, artifact_bus=bus)
    result = planner.plan(
        seed_goal="make money",
        profile="balanced",
        envelope=PermissionEnvelope(allowed_actions=[], denied_actions=[]),
        telemetry_session=session,
    )
    assert "run_id" in result
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/test_telemetry_integration.py::test_convergence_orchestrator_accepts_session -v
```
Expected: `FAILED` — `TypeError: run() got an unexpected keyword argument 'telemetry_session'`.

- [ ] **Step 3: Update `ConvergenceOrchestrator.run()` in `convergence_orchestrator.py`**

Find the `run` method signature (line 77). Change it to:

```python
def run(self, seed_task: str, resume_session_id: str | None = None, telemetry_session=None) -> ConvergenceSession:
```

The body does not need further changes -- the session is just accepted and ignored for now. It will be wired to deeper calls in Phase 16 as needed.

- [ ] **Step 4: Update `AutonomyEngine.start()` in `autonomy_engine.py`**

Find the `start` method. Change its signature to:

```python
def start(
    self,
    seed_goal: str,
    profile: str = "balanced",
    hours: int | float | None = None,
    allowed_actions: list[str] | None = None,
    denied_actions: list[str] | None = None,
    telemetry_session=None,
) -> dict:
```

- [ ] **Step 5: Update `MissionPlanner.plan()` in `mission.py`**

Change the `plan` method signature to:

```python
def plan(
    self,
    seed_goal: str,
    profile: str,
    envelope: PermissionEnvelope,
    telemetry_session=None,
) -> dict:
```

- [ ] **Step 6: Run integration tests**

```
pytest tests/test_telemetry_integration.py -v
```
Expected: all tests `PASSED`.

- [ ] **Step 7: Run full suite**

```
python3 -m pytest -q
```
Expected: no regressions.

- [ ] **Step 8: Commit**

```bash
git add src/opencobalt/core/convergence_orchestrator.py src/opencobalt/core/autonomy_engine.py src/opencobalt/core/mission.py tests/test_telemetry_integration.py
git commit -m "feat(phase15): ConvergenceOrchestrator, AutonomyEngine, MissionPlanner accept optional telemetry_session"
```

---

### Task 10: CapabilityIndex + UsageOptimizer optional session + benchmark --telemetry

**Files:**
- Modify: `src/opencobalt/core/capability_index.py`
- Modify: `src/opencobalt/core/usage_optimizer.py`
- Modify: `src/opencobalt/cli.py`

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/test_telemetry_integration.py

from opencobalt.core.capability_index import CapabilityIndex
from opencobalt.core.usage_optimizer import UsageOptimizer


def test_capability_index_accepts_session(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="route", seed_prompt="x", agent_id="claude-code")
    index = CapabilityIndex()
    # Should accept telemetry_session without error
    caps = index.discover(telemetry_session=session)
    assert isinstance(caps, list)


def test_usage_optimizer_records_agent_switch(tmp_path):
    store = TelemetryStore(tmp_path / "t.db")
    session = store.start_run(run_type="route", seed_prompt="x", agent_id="claude-code")
    ledger = MagicMock()
    ledger.list_usage_observations.return_value = []
    optimizer = UsageOptimizer(ledger=ledger)
    optimizer.choose_tool(
        task_type="tests",
        profile="max",
        router_scores={"claude-code": 10, "codex": 8},
        run_id=None,
        telemetry_session=session,
    )
    events = store.list_events(session.run_id)
    # No switch in this case -- just verify no error
    assert isinstance(events, list)
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/test_telemetry_integration.py::test_capability_index_accepts_session -v
```
Expected: `FAILED`.

- [ ] **Step 3: Update `CapabilityIndex.discover()` in `capability_index.py`**

Find the `discover` method. Change its signature to:

```python
def discover(self, telemetry_session=None) -> list[CapabilityEntry]:
```

- [ ] **Step 4: Update `UsageOptimizer.choose_tool()` in `usage_optimizer.py`**

Change the `choose_tool` signature to:

```python
def choose_tool(
    self,
    *,
    task_type: str,
    profile: str,
    router_scores: dict[str, int | float],
    run_id: str | None = None,
    telemetry_session=None,
) -> ToolChoice:
```

Inside the method body, after `tool = max(scores, key=scores.get)`, add:

```python
        if telemetry_session is not None and "benchmark" in reasons:
            # Record that we switched to a benchmark-preferred agent
            previous = max(router_scores, key=router_scores.get)
            if tool != previous:
                telemetry_session.record_agent_switch(previous, tool)
```

- [ ] **Step 5: Add `--telemetry` flag to `benchmark_status` in `cli.py`**

Find the `benchmark_status` function (around line 1918). Replace its signature with:

```python
@benchmark_app.command("status")
def benchmark_status(
    telemetry: bool = typer.Option(False, "--telemetry", help="Show category scores from telemetry store"),
) -> None:
```

Add a branch at the start of the function body:

```python
    if telemetry:
        from .core.telemetry import TelemetryStore
        t_store = TelemetryStore(_TELEMETRY_DB_PATH)
        board = t_store.get_leaderboard()
        console.print(f"\n  [bold {_COBALT}]Benchmark (Telemetry)[/bold {_COBALT}]\n")
        if not board:
            console.print("  [dim]No scored runs yet.[/dim]\n")
            return
        table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
        table.add_column("Agent", style=f"{_COBALT}")
        table.add_column("Runs", justify="right", style="dim")
        table.add_column("Overall", justify="right")
        table.add_column("Quality", justify="right", style="dim")
        table.add_column("Adherence", justify="right", style="dim")
        for entry in board:
            table.add_row(
                entry["agent_id"], str(entry["total"]),
                f"{entry['avg_overall']:.0f}",
                f"{entry.get('avg_output_quality') or 0:.0f}",
                f"{entry.get('avg_prompt_adherence') or 0:.0f}",
            )
        console.print(table)
        console.print()
        return
    # ... existing benchmark_status code continues unchanged below
```

- [ ] **Step 6: Run all integration tests and full suite**

```
pytest tests/test_telemetry_integration.py -v && python3 -m pytest -q
```
Expected: all integration tests pass, no regressions.

- [ ] **Step 7: Run public-check**

```
opencobalt public-check
```
Expected: `PASSED`.

- [ ] **Step 8: Commit**

```bash
git add src/opencobalt/core/capability_index.py src/opencobalt/core/usage_optimizer.py src/opencobalt/cli.py tests/test_telemetry_integration.py
git commit -m "feat(phase15): CapabilityIndex and UsageOptimizer accept optional session; benchmark --telemetry flag"
```

---

### Task 11: Final verification

- [ ] **Step 1: Run the full test suite**

```
python3 -m pytest -q
```
Expected: all tests pass (508 baseline + ~30 new Phase 15 tests).

- [ ] **Step 2: Smoke-test the CLI commands**

```bash
opencobalt telemetry status
opencobalt telemetry runs
opencobalt benchmark status --telemetry
```
Expected: commands run without error (empty data is fine).

- [ ] **Step 3: Run public-check**

```
opencobalt public-check
```
Expected: `PASSED`.

- [ ] **Step 4: Final commit**

```bash
git commit --allow-empty -m "feat(phase15): Phase 15 Intelligence Foundation complete"
```
