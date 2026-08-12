"""Daily Operator domain service for OpenCobalt.

Coordinates captures, commitments, focus sessions, daily reviews, priority recommendations,
execution receipts, and provenance tracing into a unified local daily control plane.
"""

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from opencobalt.core.clock import Clock, SystemClock
from opencobalt.core.daily_priority import DailyPriorityEngine
from opencobalt.core.daily_store import (
    CaptureRecord,
    CommitmentRecord,
    DailyStore,
    FocusSessionRecord,
)
from opencobalt.core.ledger import Ledger
from opencobalt.core.models import SessionEvent
from opencobalt.core.provenance import ProvenanceBuilder


class DailyOperatorService:
    """Core Daily Operator service managing Colin's daily loop."""

    def __init__(self, db_path: Path | str, clock: Optional[Clock] = None):
        self.db_path = Path(db_path)
        self.clock = clock or SystemClock()
        self.store = DailyStore(self.db_path, clock=self.clock)
        self.priority_engine = DailyPriorityEngine(clock=self.clock)
        self.ledger = Ledger(self.db_path)

    # -------------------------------------------------------------------------
    # 1. Capture
    # -------------------------------------------------------------------------
    def capture(self, raw_text: str, source: str = "cli", metadata: Optional[dict] = None) -> CaptureRecord:
        if not raw_text or not raw_text.strip():
            raise ValueError("Capture text cannot be empty.")
        rec = self.store.create_capture(raw_text.strip(), source=source, metadata=metadata)
        # Log session event in shared ledger
        self.ledger.insert_event(
            SessionEvent(
                project="daily-operator",
                source=source,
                event_type="capture_created",
                summary=f"Captured thought: '{rec.raw_text[:50]}'",
                raw_ref=rec.id,
            )
        )
        return rec

    # -------------------------------------------------------------------------
    # 2. Inbox & Clarification
    # -------------------------------------------------------------------------
    def get_inbox(self) -> List[CaptureRecord]:
        return self.store.list_captures(status="pending")

    def clarify_capture(
        self,
        capture_id: str,
        title: Optional[str] = None,
        description: str = "",
        actionable: bool = True,
        impact_level: int = 3,
        energy_level: str = "medium",
        estimated_minutes: int = 30,
        due_at: Optional[str] = None,
        mission_id: Optional[str] = None,
    ) -> Optional[CommitmentRecord]:
        cpt = self.store.get_capture(capture_id)
        if not cpt:
            raise ValueError(f"Capture ID '{capture_id}' not found.")

        if not actionable:
            self.store.update_capture_status(capture_id, "discarded")
            return None

        clean_title = title.strip() if title else cpt.raw_text.strip()
        cmt = self.store.create_commitment(
            title=clean_title,
            description=description or cpt.raw_text,
            status="ready",
            impact_level=impact_level,
            energy_level=energy_level,
            estimated_minutes=estimated_minutes,
            due_at=due_at,
            source_type="capture",
            source_ref=cpt.id,
            mission_id=mission_id,
        )
        self.store.update_capture_status(capture_id, "triaged")
        self.ledger.insert_event(
            SessionEvent(
                project="daily-operator",
                source="cli",
                event_type="capture_clarified",
                summary=f"Clarified capture {capture_id} -> commitment {cmt.id}",
                raw_ref=cmt.id,
            )
        )
        return cmt

    # -------------------------------------------------------------------------
    # 3. Today Dashboard
    # -------------------------------------------------------------------------
    def get_today_dashboard(self, active_context: Optional[dict] = None) -> Dict[str, Any]:
        now_dt = self.clock.now()
        date_stamp = now_dt.strftime("%Y-%m-%d")

        # Get active focus session
        active_focus = self.store.get_active_focus_session()
        active_focus_data = None
        if active_focus:
            cmt_title = None
            if active_focus.commitment_id:
                c_rec = self.store.get_commitment(active_focus.commitment_id)
                if c_rec:
                    cmt_title = c_rec.title
            active_focus_data = {
                "session_id": active_focus.id,
                "commitment_id": active_focus.commitment_id,
                "commitment_title": cmt_title,
                "start_time": active_focus.start_time,
                "notes": active_focus.notes,
            }

        # Get ready and active commitments
        all_commitments = self.store.list_commitments()
        inbox_count = len(self.store.list_captures(status="pending"))

        ready_items = [c for c in all_commitments if c.status in ("ready", "active")]
        waiting_items = [c for c in all_commitments if c.status == "waiting"]
        blocked_items = [c for c in all_commitments if c.status == "blocked"]
        deferred_items = [c for c in all_commitments if c.status == "deferred"]

        # Filter overdue
        overdue_items = []
        for c in ready_items + waiting_items + blocked_items:
            if c.due_at:
                try:
                    d_dt = datetime.fromisoformat(c.due_at)
                    if d_dt.tzinfo is None:
                        d_dt = d_dt.replace(tzinfo=timezone.utc)
                    if d_dt < now_dt:
                        overdue_items.append(c)
                except Exception:
                    pass

        # Sort ready items by priority score
        evaluated = self.priority_engine.sort_commitments(ready_items, active_context)

        next_action = None
        later_today = []
        if evaluated:
            top_cmt, top_exp = evaluated[0]
            next_action = {
                "commitment": asdict(top_cmt),
                "priority_score": top_exp.calculated_score,
                "explanation": top_exp.to_dict(),
            }
            for cmt, exp in evaluated[1:6]:
                later_today.append({
                    "commitment": asdict(cmt),
                    "priority_score": exp.calculated_score,
                })

        return {
            "date_stamp": date_stamp,
            "now_focus": active_focus_data,
            "next_action": next_action,
            "later_today": later_today,
            "overdue_count": len(overdue_items),
            "overdue_items": [asdict(c) for c in overdue_items],
            "waiting_count": len(waiting_items),
            "waiting_items": [asdict(c) for c in waiting_items],
            "blocked_count": len(blocked_items),
            "blocked_items": [asdict(c) for c in blocked_items],
            "deferred_count": len(deferred_items),
            "inbox_count": inbox_count,
        }

    # -------------------------------------------------------------------------
    # 4. Next Recommendation
    # -------------------------------------------------------------------------
    def get_next_recommendation(self, active_context: Optional[dict] = None) -> Optional[Dict[str, Any]]:
        ready_commitments = [c for c in self.store.list_commitments() if c.status in ("ready", "active")]
        if not ready_commitments:
            return None

        evaluated = self.priority_engine.sort_commitments(ready_commitments, active_context)
        top_cmt, top_exp = evaluated[0]

        why_outranked = []
        if len(evaluated) > 1:
            second_cmt, second_exp = evaluated[1]
            why_outranked.append(f"Outranked '{second_cmt.title}' ({second_exp.calculated_score} pts) by {top_exp.calculated_score - second_exp.calculated_score} pts.")

        return {
            "commitment": asdict(top_cmt),
            "score": top_exp.calculated_score,
            "explanation": top_exp.to_dict(),
            "why_outranked": why_outranked,
        }

    # -------------------------------------------------------------------------
    # 5. Focus Controls
    # -------------------------------------------------------------------------
    def focus_start(self, commitment_id: Optional[str] = None, notes: str = "") -> FocusSessionRecord:
        # Check if already active focus session exists
        active = self.store.get_active_focus_session()
        if active:
            self.store.end_focus_session(active.id, outcome="interrupted", notes="Auto-interrupted for new focus session.")
        return self.store.start_focus_session(commitment_id=commitment_id, notes=notes)

    def focus_status(self) -> Optional[Dict[str, Any]]:
        sess = self.store.get_active_focus_session()
        if not sess:
            return None
        cmt = self.store.get_commitment(sess.commitment_id) if sess.commitment_id else None
        now_dt = self.clock.now()
        start_dt = datetime.fromisoformat(sess.start_time)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        elapsed_mins = max(1, int((now_dt - start_dt).total_seconds() / 60))
        return {
            "session": asdict(sess),
            "commitment": asdict(cmt) if cmt else None,
            "elapsed_minutes": elapsed_mins,
        }

    def focus_stop(self, outcome: str = "completed", notes: str = "") -> Optional[FocusSessionRecord]:
        sess = self.store.get_active_focus_session()
        if not sess:
            return None
        return self.store.end_focus_session(sess.id, outcome=outcome, notes=notes)

    # -------------------------------------------------------------------------
    # 6. Completion & Outcome Receipt
    # -------------------------------------------------------------------------
    def done(
        self,
        commitment_id: str,
        outcome_summary: str = "",
        evidence_path: Optional[str] = None,
        follow_up_title: Optional[str] = None,
    ) -> Dict[str, Any]:
        cmt = self.store.get_commitment(commitment_id)
        if not cmt:
            raise ValueError(f"Commitment ID '{commitment_id}' not found.")

        updated_cmt = self.store.update_commitment_status(commitment_id, "completed", reason=outcome_summary)

        # Stop active focus session if matching
        active_sess = self.store.get_active_focus_session()
        if active_sess and active_sess.commitment_id == commitment_id:
            self.store.end_focus_session(active_sess.id, outcome="completed", notes=outcome_summary)

        # Record outcome to SQLite ledger
        self.ledger.insert_outcome(
            task_id=commitment_id,
            tool="daily_operator",
            outcome=outcome_summary or "Completed commitment",
            metadata={"evidence_path": evidence_path, "completed_at": self.clock.now_iso()},
        )

        follow_up_rec = None
        if follow_up_title:
            follow_up_rec = self.store.create_commitment(
                title=follow_up_title,
                source_type="commitment",
                source_ref=commitment_id,
                status="ready",
            )

        return {
            "commitment": asdict(updated_cmt),
            "outcome_summary": outcome_summary or "Completed",
            "evidence_path": evidence_path,
            "follow_up": asdict(follow_up_rec) if follow_up_rec else None,
        }

    # -------------------------------------------------------------------------
    # 7. Defer & Waiting State Controls
    # -------------------------------------------------------------------------
    def defer(self, commitment_id: str, until_iso: str, reason: str = "") -> CommitmentRecord:
        cmt = self.store.update_commitment_status(commitment_id, "deferred", reason=reason, deferred_until=until_iso)
        if not cmt:
            raise ValueError(f"Commitment ID '{commitment_id}' not found.")
        return cmt

    def waiting(self, commitment_id: str, for_ref: str, reason: str = "") -> CommitmentRecord:
        cmt = self.store.update_commitment_status(commitment_id, "waiting", reason=reason, waiting_on_ref=for_ref)
        if not cmt:
            raise ValueError(f"Commitment ID '{commitment_id}' not found.")
        return cmt

    # -------------------------------------------------------------------------
    # 8. Daily Review Protocol
    # -------------------------------------------------------------------------
    def review_day(self, date_stamp: Optional[str] = None) -> Dict[str, Any]:
        target_date = date_stamp or self.clock.now().strftime("%Y-%m-%d")
        all_commitments = self.store.list_commitments()

        completed_today = [c for c in all_commitments if c.status == "completed" and c.completed_at and c.completed_at.startswith(target_date)]
        deferred_today = [c for c in all_commitments if c.status == "deferred"]
        waiting_today = [c for c in all_commitments if c.status == "waiting"]
        inbox_count = len(self.store.list_captures(status="pending"))

        scorecard = {
            "date": target_date,
            "completed_count": len(completed_today),
            "deferred_count": len(deferred_today),
            "waiting_count": len(waiting_today),
            "inbox_count": inbox_count,
        }

        rev = self.store.save_daily_review(
            date_stamp=target_date,
            evening_review={"completed_items": [c.id for c in completed_today]},
            scorecard=scorecard,
        )

        return {
            "review": asdict(rev),
            "scorecard": scorecard,
            "completed_items": [asdict(c) for c in completed_today],
            "deferred_items": [asdict(c) for c in deferred_today],
            "waiting_items": [asdict(c) for c in waiting_today],
        }

    # -------------------------------------------------------------------------
    # 9. Search & Why Lineage Integration
    # -------------------------------------------------------------------------
    def search(self, query: str) -> Dict[str, Any]:
        q_lower = query.lower()
        captures = [asdict(c) for c in self.store.list_captures() if q_lower in c.raw_text.lower()]
        commitments = [
            asdict(c) for c in self.store.list_commitments()
            if q_lower in c.title.lower() or q_lower in c.description.lower()
        ]
        return {
            "query": query,
            "captures": captures,
            "commitments": commitments,
        }

    def why(self, entity_id: str) -> Dict[str, Any]:
        """Traces lineage of an entity via ProvenanceBuilder or daily store lineage."""
        builder = ProvenanceBuilder(self.db_path)
        trace = builder.trace(entity_id)

        # Check if entity is in daily store
        cmt = self.store.get_commitment(entity_id)
        cpt = self.store.get_capture(entity_id)
        daily_metadata = {}
        if cmt:
            daily_metadata["type"] = "commitment"
            daily_metadata["commitment"] = asdict(cmt)
            daily_metadata["events"] = [asdict(e) for e in self.store.list_events_for_commitment(cmt.id)]
        elif cpt:
            daily_metadata["type"] = "capture"
            daily_metadata["capture"] = asdict(cpt)

        trace_dict = None
        if trace:
            trace_dict = {
                "focus_id": trace.focus_id,
                "focus_kind": trace.focus_kind,
                "nodes": [asdict(n) for n in trace.nodes],
                "edges": [asdict(e) for e in trace.edges],
            }

        return {
            "entity_id": entity_id,
            "provenance_trace": trace_dict,
            "daily_metadata": daily_metadata,
        }
