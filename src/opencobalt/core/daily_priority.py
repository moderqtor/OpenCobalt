"""Transparent, deterministic priority calculation engine for OpenCobalt daily operator."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from opencobalt.core.clock import Clock, SystemClock
from opencobalt.core.daily_store import CommitmentRecord


@dataclass
class PriorityExplanation:
    commitment_id: str
    calculated_score: int
    calculated_at: str
    components: Dict[str, int]
    rationale: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "commitment_id": self.commitment_id,
            "calculated_score": self.calculated_score,
            "calculated_at": self.calculated_at,
            "components": self.components,
            "rationale": self.rationale,
        }


class DailyPriorityEngine:
    """Calculates transparent, reproducible priority scores for commitments."""

    def __init__(self, clock: Optional[Clock] = None):
        self.clock = clock or SystemClock()

    def evaluate(
        self,
        commitment: CommitmentRecord,
        active_context: Optional[Dict[str, Any]] = None,
    ) -> PriorityExplanation:
        now_dt = self.clock.now()
        now_iso = self.clock.now_iso()
        rationale: List[str] = []

        # 1. Base Score
        base_score = 100
        rationale.append("+100 base task priority")

        # 2. Urgency Score
        urgency_score = 0
        if commitment.due_at:
            try:
                due_dt = datetime.fromisoformat(commitment.due_at)
                if due_dt.tzinfo is None:
                    due_dt = due_dt.replace(tzinfo=timezone.utc)
                hours_remaining = (due_dt - now_dt).total_seconds() / 3600.0

                if hours_remaining < 0:
                    overdue_hours = abs(hours_remaining)
                    urgency_score = min(400, int(300 + 10 * overdue_hours))
                    rationale.append(f"+{urgency_score} OVERDUE by {overdue_hours:.1f} hours")
                elif hours_remaining <= 24.0:
                    urgency_score = int(300.0 * (1.0 - (hours_remaining / 24.0)))
                    rationale.append(f"+{urgency_score} due within 24 hours ({hours_remaining:.1f}h remaining)")
                else:
                    days_rem = hours_remaining / 24.0
                    urgency_score = max(0, int(100 - 2 * days_rem))
                    rationale.append(f"+{urgency_score} due in {days_rem:.1f} days")
            except Exception:
                urgency_score = 0
                rationale.append("+0 invalid due_at timestamp")

        # 3. Impact Score
        impact_map = {1: 0, 2: 50, 3: 100, 4: 180, 5: 250}
        impact_score = impact_map.get(commitment.impact_level, 100)
        rationale.append(f"+{impact_score} impact rating (level {commitment.impact_level})")

        # 4. Staleness Score
        staleness_score = 0
        try:
            created_dt = datetime.fromisoformat(commitment.created_at)
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
            days_stale = (now_dt - created_dt).total_seconds() / 86400.0
            if days_stale > 0 and commitment.status == "ready":
                staleness_score = min(100, int(days_stale * 10))
                rationale.append(f"+{staleness_score} stale in ready state for {days_stale:.1f} days")
        except Exception:
            staleness_score = 0

        # 5. Penalties
        penalty_score = 0
        if commitment.status == "blocked":
            penalty_score = 300
            rationale.append("-300 penalty: status is blocked")
        elif commitment.status == "waiting":
            penalty_score = 200
            rationale.append("-200 penalty: status is waiting")
        elif commitment.status == "deferred":
            penalty_score = 400
            rationale.append("-400 penalty: status is deferred")

        # 6. Context Match Bonus
        context_bonus = 0
        if active_context:
            if active_context.get("energy") and active_context["energy"] == commitment.energy_level:
                context_bonus += 50
                rationale.append("+50 matches requested energy level")
            if active_context.get("max_minutes") and commitment.estimated_minutes <= active_context["max_minutes"]:
                context_bonus += 50
                rationale.append(f"+50 fits inside time window ({commitment.estimated_minutes}m <= {active_context['max_minutes']}m)")

        raw_score = base_score + urgency_score + impact_score + staleness_score - penalty_score + context_bonus
        final_score = max(0, min(1000, raw_score))

        components = {
            "base_score": base_score,
            "urgency_score": urgency_score,
            "impact_score": impact_score,
            "staleness_score": staleness_score,
            "penalty_score": penalty_score,
            "context_bonus": context_bonus,
        }

        return PriorityExplanation(
            commitment_id=commitment.id,
            calculated_score=final_score,
            calculated_at=now_iso,
            components=components,
            rationale=rationale,
        )

    def sort_commitments(
        self,
        commitments: List[CommitmentRecord],
        active_context: Optional[Dict[str, Any]] = None,
    ) -> List[tuple[CommitmentRecord, PriorityExplanation]]:
        """Sort commitments deterministically by priority score DESC, due_at ASC, created_at ASC, id ASC."""
        evaluated = [(cmt, self.evaluate(cmt, active_context)) for cmt in commitments]

        def sort_key(item: tuple[CommitmentRecord, PriorityExplanation]):
            cmt, exp = item
            due_str = cmt.due_at or "9999-12-31T23:59:59"
            return (
                -exp.calculated_score,  # Higher score first
                due_str,                # Earlier deadline first
                cmt.created_at,         # Older task first
                cmt.id,                 # Lexicographical fallback tie-breaker
            )

        return sorted(evaluated, key=sort_key)
