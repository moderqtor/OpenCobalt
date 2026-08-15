"""Telemetry capture store for OpenCobalt runs."""
from __future__ import annotations

import json
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


class TelemetryStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self):
        from opencobalt.core.sqlite import closing_sqlite

        return closing_sqlite(self.db_path)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def start_run(
        self,
        *,
        run_type: str,
        seed_prompt: str,
        agent_id: str,
        subagent_id: str | None = None,
        model_used: str = "",
    ) -> TelemetrySession:
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
            if row is None and len(run_id) < 36:
                rows = conn.execute(
                    "SELECT * FROM telemetry_runs WHERE id LIKE ?", (run_id + "%",)
                ).fetchall()
                row = rows[0] if len(rows) == 1 else None
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
            conn.execute(
                "UPDATE telemetry_runs SET status='scored' WHERE id=?", (score["run_id"],)
            )

    def get_score(self, run_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM telemetry_scores WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None and len(run_id) < 36:
                rows = conn.execute(
                    "SELECT * FROM telemetry_scores WHERE run_id LIKE ?", (run_id + "%",)
                ).fetchall()
                row = rows[0] if len(rows) == 1 else None
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
