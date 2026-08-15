"""SQLite persistence for opportunity runs, tracks, and outcomes.

Lives in the same ledger database as the rest of OpenCobalt state. Tables
use CREATE TABLE IF NOT EXISTS so existing databases are never broken.
The full run is stored as JSON for lossless replay; tracks get scalar
columns (score, risk, status) so the UI and future learned routing can
query them without decoding JSON.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .opportunity_engine import OpportunityRun

_DEFAULT_DB = Path(".opencobalt") / "ledger.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunity_runs (
    run_id     TEXT PRIMARY KEY,
    goal_text  TEXT NOT NULL,
    goal_class TEXT NOT NULL,
    created_at TEXT NOT NULL,
    run_json   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS opportunity_tracks (
    track_id       TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL,
    name           TEXT NOT NULL,
    track_type     TEXT NOT NULL,
    status         TEXT NOT NULL,
    score_total    REAL,
    plan_id        TEXT,
    evidence_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS opportunity_outcomes (
    outcome_id TEXT PRIMARY KEY,
    track_id   TEXT NOT NULL,
    plan_id    TEXT,
    receipt_id TEXT,
    outcome    TEXT NOT NULL,
    notes      TEXT,
    created_at TEXT NOT NULL
);
"""

OUTCOME_VALUES = ("useful", "neutral", "wasted", "abandoned")


class OpportunityStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = (db_path or _DEFAULT_DB).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self):
        from opencobalt.core.sqlite import closing_sqlite

        return closing_sqlite(self.db_path)

    # --- Runs ---

    def save_run(self, run: OpportunityRun) -> None:
        totals = {s.track_id: s.total for s in run.scores}
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO opportunity_runs VALUES (?,?,?,?,?)",
                (
                    run.run_id,
                    run.goal.text,
                    run.goal.goal_class,
                    run.created_at,
                    json.dumps(run.to_dict(), sort_keys=True),
                ),
            )
            for track in run.tracks:
                conn.execute(
                    "INSERT OR REPLACE INTO opportunity_tracks VALUES (?,?,?,?,?,?,?,?)",
                    (
                        track.track_id,
                        run.run_id,
                        track.name,
                        track.track_type,
                        track.status,
                        totals.get(track.track_id),
                        track.plan_id,
                        len(track.evidence_ids),
                    ),
                )

    def get_run(self, run_id: str) -> OpportunityRun | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT run_json FROM opportunity_runs WHERE run_id = ? OR run_id LIKE ?",
                (run_id, f"{run_id}%"),
            ).fetchone()
        return OpportunityRun.from_dict(json.loads(row["run_json"])) if row else None

    def latest_run(self) -> OpportunityRun | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT run_json FROM opportunity_runs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return OpportunityRun.from_dict(json.loads(row["run_json"])) if row else None

    def list_runs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT run_id, goal_text, goal_class, created_at "
                "FROM opportunity_runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def find_run_for_track(self, track_id: str) -> OpportunityRun | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT run_id FROM opportunity_tracks "
                "WHERE track_id = ? OR track_id LIKE ?",
                (track_id, f"{track_id}%"),
            ).fetchone()
        return self.get_run(row["run_id"]) if row else None

    def find_run_for_plan(self, plan_id: str) -> OpportunityRun | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT run_id FROM opportunity_tracks "
                "WHERE plan_id = ? OR plan_id LIKE ?",
                (plan_id, f"{plan_id}%"),
            ).fetchone()
        return self.get_run(row["run_id"]) if row else None

    # --- Outcomes (feedback for future learned routing) ---

    def record_outcome(
        self,
        track_id: str,
        *,
        outcome: str,
        plan_id: str | None = None,
        receipt_id: str | None = None,
        notes: str | None = None,
    ) -> str:
        if outcome not in OUTCOME_VALUES:
            raise ValueError(f"unknown outcome: {outcome} (use one of {OUTCOME_VALUES})")
        outcome_id = f"oout-{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO opportunity_outcomes VALUES (?,?,?,?,?,?,?)",
                (
                    outcome_id,
                    track_id,
                    plan_id,
                    receipt_id,
                    outcome,
                    notes,
                    datetime.now(tz=timezone.utc).isoformat(),
                ),
            )
        return outcome_id

    def outcome_stats_by_track_type(self) -> dict[str, dict[str, int]]:
        """Outcome counts grouped by track type, for outcome-weighted scoring."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT t.track_type AS track_type, o.outcome AS outcome, "
                "COUNT(*) AS n "
                "FROM opportunity_outcomes o "
                "JOIN opportunity_tracks t ON t.track_id = o.track_id "
                "GROUP BY t.track_type, o.outcome"
            ).fetchall()
        stats: dict[str, dict[str, int]] = {}
        for row in rows:
            stats.setdefault(row["track_type"], {})[row["outcome"]] = int(row["n"])
        return stats

    def list_outcomes(self, *, track_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        sql = "SELECT * FROM opportunity_outcomes"
        params: list[Any] = []
        if track_id:
            sql += " WHERE track_id = ?"
            params.append(track_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
