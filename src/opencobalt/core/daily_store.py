"""SQLite storage for OpenCobalt Daily Operator thin entities."""

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from opencobalt.core.clock import Clock, SystemClock


@dataclass
class CaptureRecord:
    id: str
    raw_text: str
    source: str = "cli"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    triaged_at: Optional[str] = None
    status: str = "pending"  # pending, triaged, discarded
    metadata: str = "{}"


@dataclass
class CommitmentRecord:
    id: str
    title: str
    description: str = ""
    status: str = "inbox"  # inbox, ready, active, waiting, blocked, deferred, completed, cancelled, archived
    impact_level: int = 3  # 1 to 5
    energy_level: str = "medium"  # low, medium, high
    estimated_minutes: int = 30
    due_at: Optional[str] = None
    deferred_until: Optional[str] = None
    blocked_by_ref: Optional[str] = None
    waiting_on_ref: Optional[str] = None
    source_type: str = "manual"  # manual, capture, opportunity, mission
    source_ref: Optional[str] = None
    mission_id: Optional[str] = None
    opportunity_id: Optional[str] = None
    parent_commitment_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None


@dataclass
class FocusSessionRecord:
    id: str
    commitment_id: Optional[str]
    start_time: str
    end_time: Optional[str] = None
    duration_minutes: Optional[int] = None
    outcome: str = "in_progress"  # in_progress, completed, interrupted, abandoned
    notes: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class DailyReviewRecord:
    id: str
    date_stamp: str  # YYYY-MM-DD
    morning_plan_json: str = "{}"
    evening_review_json: str = "{}"
    scorecard_json: str = "{}"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class CommitmentEventRecord:
    id: str
    commitment_id: str
    timestamp: str
    event_type: str  # created, state_changed, priority_recalculated, linked_to_mission, completed
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    payload_json: str = "{}"


class DailyStore:
    """Store for daily operator captures, commitments, focus sessions, and reviews."""

    def __init__(self, db_path: Path | str, clock: Optional[Clock] = None):
        self.db_path = Path(db_path)
        self.clock = clock or SystemClock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        """Initialize database schema idempotently."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_conn() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version     INTEGER PRIMARY KEY,
                    name        TEXT NOT NULL,
                    applied_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS captures (
                    id          TEXT PRIMARY KEY,
                    raw_text    TEXT NOT NULL,
                    source      TEXT NOT NULL DEFAULT 'cli',
                    created_at  TEXT NOT NULL,
                    triaged_at  TEXT,
                    status      TEXT NOT NULL DEFAULT 'pending',
                    metadata    TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS commitments (
                    id                    TEXT PRIMARY KEY,
                    title                 TEXT NOT NULL,
                    description           TEXT NOT NULL DEFAULT '',
                    status                TEXT NOT NULL DEFAULT 'inbox',
                    impact_level          INTEGER NOT NULL DEFAULT 3,
                    energy_level          TEXT NOT NULL DEFAULT 'medium',
                    estimated_minutes     INTEGER NOT NULL DEFAULT 30,
                    due_at                TEXT,
                    deferred_until        TEXT,
                    blocked_by_ref        TEXT,
                    waiting_on_ref        TEXT,
                    source_type           TEXT NOT NULL DEFAULT 'manual',
                    source_ref            TEXT,
                    mission_id            TEXT,
                    opportunity_id        TEXT,
                    parent_commitment_id  TEXT,
                    created_at            TEXT NOT NULL,
                    updated_at            TEXT NOT NULL,
                    completed_at          TEXT,
                    FOREIGN KEY (parent_commitment_id) REFERENCES commitments(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS focus_sessions (
                    id              TEXT PRIMARY KEY,
                    commitment_id   TEXT,
                    start_time      TEXT NOT NULL,
                    end_time        TEXT,
                    duration_minutes INTEGER,
                    outcome         TEXT NOT NULL DEFAULT 'in_progress',
                    notes           TEXT NOT NULL DEFAULT '',
                    created_at      TEXT NOT NULL,
                    FOREIGN KEY (commitment_id) REFERENCES commitments(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS daily_reviews (
                    id                  TEXT PRIMARY KEY,
                    date_stamp          TEXT UNIQUE NOT NULL,
                    morning_plan_json   TEXT NOT NULL DEFAULT '{}',
                    evening_review_json TEXT NOT NULL DEFAULT '{}',
                    scorecard_json      TEXT NOT NULL DEFAULT '{}',
                    created_at          TEXT NOT NULL,
                    updated_at          TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS commitment_events (
                    id            TEXT PRIMARY KEY,
                    commitment_id TEXT NOT NULL,
                    timestamp     TEXT NOT NULL,
                    event_type    TEXT NOT NULL,
                    from_status   TEXT,
                    to_status     TEXT,
                    payload_json  TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (commitment_id) REFERENCES commitments(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_commitments_status_due ON commitments(status, due_at);
                CREATE INDEX IF NOT EXISTS idx_commitments_provenance ON commitments(source_type, source_ref);
                CREATE INDEX IF NOT EXISTS idx_focus_sessions_commitment ON focus_sessions(commitment_id);
                CREATE INDEX IF NOT EXISTS idx_commitment_events_commitment ON commitment_events(commitment_id, timestamp);
                """
            )
            # Add append-only triggers on commitment_events if not present
            conn.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS commitment_events_no_update
                BEFORE UPDATE ON commitment_events
                BEGIN
                    SELECT RAISE(ABORT, 'commitment_events table is append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS commitment_events_no_delete
                BEFORE DELETE ON commitment_events
                BEGIN
                    SELECT RAISE(ABORT, 'commitment_events table is append-only');
                END;
                """
            )

    # -------------------------------------------------------------------------
    # Capture Methods
    # -------------------------------------------------------------------------
    def create_capture(self, raw_text: str, source: str = "cli", metadata: Optional[dict] = None) -> CaptureRecord:
        cpt_id = f"cpt-{uuid.uuid4().hex[:12]}"
        now_str = self.clock.now_iso()
        meta_str = json.dumps(metadata or {})
        rec = CaptureRecord(
            id=cpt_id,
            raw_text=raw_text,
            source=source,
            created_at=now_str,
            status="pending",
            metadata=meta_str,
        )
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO captures (id, raw_text, source, created_at, status, metadata) VALUES (?, ?, ?, ?, ?, ?)",
                (rec.id, rec.raw_text, rec.source, rec.created_at, rec.status, rec.metadata),
            )
        return rec

    def list_captures(self, status: Optional[str] = "pending") -> List[CaptureRecord]:
        with self._get_conn() as conn:
            if status:
                cursor = conn.execute("SELECT * FROM captures WHERE status = ? ORDER BY created_at ASC", (status,))
            else:
                cursor = conn.execute("SELECT * FROM captures ORDER BY created_at ASC")
            rows = cursor.fetchall()
            return [CaptureRecord(**dict(row)) for row in rows]

    def get_capture(self, capture_id: str) -> Optional[CaptureRecord]:
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT * FROM captures WHERE id = ?", (capture_id,))
            row = cursor.fetchone()
            return CaptureRecord(**dict(row)) if row else None

    def update_capture_status(self, capture_id: str, status: str) -> None:
        now_str = self.clock.now_iso()
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE captures SET status = ?, triaged_at = ? WHERE id = ?",
                (status, now_str, capture_id),
            )

    # -------------------------------------------------------------------------
    # Commitment Methods
    # -------------------------------------------------------------------------
    def create_commitment(
        self,
        title: str,
        description: str = "",
        status: str = "inbox",
        impact_level: int = 3,
        energy_level: str = "medium",
        estimated_minutes: int = 30,
        due_at: Optional[str] = None,
        deferred_until: Optional[str] = None,
        blocked_by_ref: Optional[str] = None,
        waiting_on_ref: Optional[str] = None,
        source_type: str = "manual",
        source_ref: Optional[str] = None,
        mission_id: Optional[str] = None,
        opportunity_id: Optional[str] = None,
        parent_commitment_id: Optional[str] = None,
    ) -> CommitmentRecord:
        cmt_id = f"cmt-{uuid.uuid4().hex[:12]}"
        now_str = self.clock.now_iso()
        rec = CommitmentRecord(
            id=cmt_id,
            title=title,
            description=description,
            status=status,
            impact_level=impact_level,
            energy_level=energy_level,
            estimated_minutes=estimated_minutes,
            due_at=due_at,
            deferred_until=deferred_until,
            blocked_by_ref=blocked_by_ref,
            waiting_on_ref=waiting_on_ref,
            source_type=source_type,
            source_ref=source_ref,
            mission_id=mission_id,
            opportunity_id=opportunity_id,
            parent_commitment_id=parent_commitment_id,
            created_at=now_str,
            updated_at=now_str,
        )
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO commitments (
                    id, title, description, status, impact_level, energy_level, estimated_minutes,
                    due_at, deferred_until, blocked_by_ref, waiting_on_ref, source_type, source_ref,
                    mission_id, opportunity_id, parent_commitment_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.id, rec.title, rec.description, rec.status, rec.impact_level, rec.energy_level,
                    rec.estimated_minutes, rec.due_at, rec.deferred_until, rec.blocked_by_ref, rec.waiting_on_ref,
                    rec.source_type, rec.source_ref, rec.mission_id, rec.opportunity_id, rec.parent_commitment_id,
                    rec.created_at, rec.updated_at,
                ),
            )
            # Log creation audit event
            self._log_event(
                conn,
                commitment_id=rec.id,
                event_type="created",
                to_status=rec.status,
                payload={"title": rec.title, "source_type": rec.source_type, "source_ref": rec.source_ref},
            )
        return rec

    def get_commitment(self, cmt_id: str) -> Optional[CommitmentRecord]:
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT * FROM commitments WHERE id = ?", (cmt_id,))
            row = cursor.fetchone()
            return CommitmentRecord(**dict(row)) if row else None

    def list_commitments(self, status: Optional[str] = None) -> List[CommitmentRecord]:
        with self._get_conn() as conn:
            if status:
                cursor = conn.execute("SELECT * FROM commitments WHERE status = ? ORDER BY created_at DESC", (status,))
            else:
                cursor = conn.execute("SELECT * FROM commitments ORDER BY created_at DESC")
            rows = cursor.fetchall()
            return [CommitmentRecord(**dict(row)) for row in rows]

    def update_commitment_status(
        self,
        cmt_id: str,
        new_status: str,
        reason: Optional[str] = None,
        deferred_until: Optional[str] = None,
        waiting_on_ref: Optional[str] = None,
        blocked_by_ref: Optional[str] = None,
    ) -> Optional[CommitmentRecord]:
        cmt = self.get_commitment(cmt_id)
        if not cmt:
            return None
        old_status = cmt.status
        now_str = self.clock.now_iso()
        completed_at = now_str if new_status == "completed" else cmt.completed_at

        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE commitments SET
                    status = ?,
                    updated_at = ?,
                    completed_at = ?,
                    deferred_until = COALESCE(?, deferred_until),
                    waiting_on_ref = COALESCE(?, waiting_on_ref),
                    blocked_by_ref = COALESCE(?, blocked_by_ref)
                WHERE id = ?
                """,
                (new_status, now_str, completed_at, deferred_until, waiting_on_ref, blocked_by_ref, cmt_id),
            )
            payload = {}
            if reason:
                payload["reason"] = reason
            if deferred_until:
                payload["deferred_until"] = deferred_until
            if waiting_on_ref:
                payload["waiting_on_ref"] = waiting_on_ref
            if blocked_by_ref:
                payload["blocked_by_ref"] = blocked_by_ref

            self._log_event(
                conn,
                commitment_id=cmt_id,
                event_type="state_changed",
                from_status=old_status,
                to_status=new_status,
                payload=payload,
            )
        return self.get_commitment(cmt_id)

    # -------------------------------------------------------------------------
    # Focus Session Methods
    # -------------------------------------------------------------------------
    def start_focus_session(self, commitment_id: Optional[str] = None, notes: str = "") -> FocusSessionRecord:
        fcs_id = f"fcs-{uuid.uuid4().hex[:12]}"
        now_str = self.clock.now_iso()
        rec = FocusSessionRecord(
            id=fcs_id,
            commitment_id=commitment_id,
            start_time=now_str,
            outcome="in_progress",
            notes=notes,
            created_at=now_str,
        )
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO focus_sessions (id, commitment_id, start_time, outcome, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (rec.id, rec.commitment_id, rec.start_time, rec.outcome, rec.notes, rec.created_at),
            )
            if commitment_id:
                # Set commitment status to active
                conn.execute(
                    "UPDATE commitments SET status = 'active', updated_at = ? WHERE id = ?",
                    (now_str, commitment_id),
                )
                self._log_event(
                    conn,
                    commitment_id=commitment_id,
                    event_type="state_changed",
                    from_status="ready",
                    to_status="active",
                    payload={"focus_session_id": fcs_id},
                )
        return rec

    def get_active_focus_session(self) -> Optional[FocusSessionRecord]:
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT * FROM focus_sessions WHERE outcome = 'in_progress' ORDER BY start_time DESC LIMIT 1")
            row = cursor.fetchone()
            return FocusSessionRecord(**dict(row)) if row else None

    def end_focus_session(self, session_id: str, outcome: str = "completed", notes: str = "") -> Optional[FocusSessionRecord]:
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT * FROM focus_sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            if not row:
                return None
            sess = FocusSessionRecord(**dict(row))
            now_str = self.clock.now_iso()

            # Calculate duration in minutes
            start_dt = datetime.fromisoformat(sess.start_time)
            end_dt = datetime.fromisoformat(now_str)
            duration_mins = max(1, int((end_dt - start_dt).total_seconds() / 60))

            full_notes = f"{sess.notes}\n{notes}".strip() if notes else sess.notes

            conn.execute(
                """
                UPDATE focus_sessions SET
                    end_time = ?,
                    duration_minutes = ?,
                    outcome = ?,
                    notes = ?
                WHERE id = ?
                """,
                (now_str, duration_mins, outcome, full_notes, session_id),
            )

            if sess.commitment_id and outcome in ("completed", "interrupted", "abandoned"):
                new_cmt_status = "completed" if outcome == "completed" else "ready"
                current = conn.execute(
                    "SELECT status FROM commitments WHERE id = ?",
                    (sess.commitment_id,),
                ).fetchone()
                current_status = current["status"] if current else None
                if current_status is not None and current_status != new_cmt_status:
                    conn.execute(
                        "UPDATE commitments SET status = ?, updated_at = ? WHERE id = ?",
                        (new_cmt_status, now_str, sess.commitment_id),
                    )
                    self._log_event(
                        conn,
                        commitment_id=sess.commitment_id,
                        event_type="state_changed",
                        from_status=current_status,
                        to_status=new_cmt_status,
                        payload={"focus_session_id": session_id, "duration_minutes": duration_mins, "outcome": outcome},
                    )

        with self._get_conn() as conn:
            cursor = conn.execute("SELECT * FROM focus_sessions WHERE id = ?", (session_id,))
            return FocusSessionRecord(**dict(cursor.fetchone()))

    # -------------------------------------------------------------------------
    # Daily Review Methods
    # -------------------------------------------------------------------------
    def get_or_create_daily_review(self, date_stamp: str) -> DailyReviewRecord:
        now_str = self.clock.now_iso()
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT * FROM daily_reviews WHERE date_stamp = ?", (date_stamp,))
            row = cursor.fetchone()
            if row:
                return DailyReviewRecord(**dict(row))
            drv_id = f"drv-{uuid.uuid4().hex[:12]}"
            conn.execute(
                "INSERT INTO daily_reviews (id, date_stamp, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (drv_id, date_stamp, now_str, now_str),
            )
            cursor = conn.execute("SELECT * FROM daily_reviews WHERE id = ?", (drv_id,))
            return DailyReviewRecord(**dict(cursor.fetchone()))

    def save_daily_review(
        self, date_stamp: str, morning_plan: Optional[dict] = None, evening_review: Optional[dict] = None, scorecard: Optional[dict] = None
    ) -> DailyReviewRecord:
        rec = self.get_or_create_daily_review(date_stamp)
        now_str = self.clock.now_iso()
        m_json = json.dumps(morning_plan) if morning_plan is not None else rec.morning_plan_json
        e_json = json.dumps(evening_review) if evening_review is not None else rec.evening_review_json
        s_json = json.dumps(scorecard) if scorecard is not None else rec.scorecard_json

        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE daily_reviews SET
                    morning_plan_json = ?,
                    evening_review_json = ?,
                    scorecard_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (m_json, e_json, s_json, now_str, rec.id),
            )
            cursor = conn.execute("SELECT * FROM daily_reviews WHERE id = ?", (rec.id,))
            return DailyReviewRecord(**dict(cursor.fetchone()))

    # -------------------------------------------------------------------------
    # Event Audit Helper
    # -------------------------------------------------------------------------
    def _log_event(
        self,
        conn: sqlite3.Connection,
        commitment_id: str,
        event_type: str,
        from_status: Optional[str] = None,
        to_status: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> None:
        evt_id = f"cev-{uuid.uuid4().hex[:12]}"
        now_str = self.clock.now_iso()
        conn.execute(
            """
            INSERT INTO commitment_events (id, commitment_id, timestamp, event_type, from_status, to_status, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (evt_id, commitment_id, now_str, event_type, from_status, to_status, json.dumps(payload or {})),
        )

    def list_events_for_commitment(self, commitment_id: str) -> List[CommitmentEventRecord]:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT * FROM commitment_events WHERE commitment_id = ? ORDER BY timestamp ASC",
                (commitment_id,),
            )
            return [CommitmentEventRecord(**dict(row)) for row in cursor.fetchall()]
