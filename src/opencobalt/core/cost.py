"""Cost tracking and budget control for OpenCobalt.

Uses stdlib sqlite3 only. Additive new tables; no changes to existing schema.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Helpers shared with models.py style
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _uid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class CostRecord(BaseModel):
    id: str = Field(default_factory=_uid)
    timestamp: datetime = Field(default_factory=_now)
    model_id: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    routing_mode: str
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Model registry
# Keys are model_id strings; values are per-1k-token rates in USD.
# ---------------------------------------------------------------------------

VALID_ROUTING_MODES = {"cheap", "standard", "frontier"}

MODEL_REGISTRY: dict[str, dict[str, Any]] = {
    "claude-opus-4": {
        "cost_per_1k_input": 0.015,
        "cost_per_1k_output": 0.075,
        "tier": "frontier",
    },
    "claude-sonnet-4-6": {
        "cost_per_1k_input": 0.003,
        "cost_per_1k_output": 0.015,
        "tier": "standard",
    },
    "gpt-4o": {
        "cost_per_1k_input": 0.005,
        "cost_per_1k_output": 0.015,
        "tier": "standard",
    },
    "gemini-pro": {
        "cost_per_1k_input": 0.0005,
        "cost_per_1k_output": 0.0015,
        "tier": "cheap",
    },
    "ollama": {
        "cost_per_1k_input": 0.0,
        "cost_per_1k_output": 0.0,
        "tier": "worker",
    },
}

# ---------------------------------------------------------------------------
# SQLite schema (additive only)
# ---------------------------------------------------------------------------

_COST_SCHEMA = """
CREATE TABLE IF NOT EXISTS cost_records (
    id            TEXT PRIMARY KEY,
    timestamp     TEXT NOT NULL,
    model_id      TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd      REAL NOT NULL,
    routing_mode  TEXT NOT NULL,
    metadata      TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS cost_config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_DEFAULT_PER_RUN_CAP = 0.10
_DEFAULT_MONTHLY_CAP = 5.00
_DEFAULT_ROUTING_MODE = "standard"


# ---------------------------------------------------------------------------
# CostTracker
# ---------------------------------------------------------------------------

class CostTracker:
    """Tracks per-run costs and manages routing mode.

    # Cap estimation not yet implemented at adapter layer -- this tracks spend only.
    All state lives in the SQLite DB at db_path.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_COST_SCHEMA)

    def _config_get(self, key: str, default: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM cost_config WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def _config_set(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cost_config (key, value) VALUES (?, ?)",
                (key, value),
            )

    # ------------------------------------------------------------------
    # Cost calculation
    # ------------------------------------------------------------------

    def estimate_cost(self, model_id: str, input_tokens: int, output_tokens: int) -> float:
        """Return estimated cost in USD without writing to the DB.

        Returns 0.0 for unknown model_id rather than raising.
        """
        entry = MODEL_REGISTRY.get(model_id)
        if entry is None:
            return 0.0
        cost = (
            input_tokens / 1000.0 * entry["cost_per_1k_input"]
            + output_tokens / 1000.0 * entry["cost_per_1k_output"]
        )
        return round(cost, 10)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def record_run(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        routing_mode: str,
        metadata: dict[str, Any] | None = None,
    ) -> CostRecord:
        """Compute cost, persist to DB, and return the resulting CostRecord."""
        cost = self.estimate_cost(model_id, input_tokens, output_tokens)
        record = CostRecord(
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            routing_mode=routing_mode,
            metadata=metadata or {},
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO cost_records VALUES (?,?,?,?,?,?,?,?)",
                (
                    record.id,
                    record.timestamp.isoformat(),
                    record.model_id,
                    record.input_tokens,
                    record.output_tokens,
                    record.cost_usd,
                    record.routing_mode,
                    json.dumps(record.metadata),
                ),
            )
        return record

    # ------------------------------------------------------------------
    # Spend aggregates
    # ------------------------------------------------------------------

    def monthly_spend(self) -> float:
        """Sum of cost_usd for all records in the current UTC calendar month."""
        now = _now()
        # ISO prefix for the current year-month, e.g. "2026-05"
        month_prefix = now.strftime("%Y-%m")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0.0) FROM cost_records"
                " WHERE timestamp LIKE ?",
                (f"{month_prefix}%",),
            ).fetchone()
        return float(row[0])

    # ------------------------------------------------------------------
    # Config accessors
    # ------------------------------------------------------------------

    def per_run_cap(self) -> float:
        """Maximum allowed cost per individual run, in USD."""
        return float(self._config_get("per_run_cap", str(_DEFAULT_PER_RUN_CAP)))

    def monthly_cap(self) -> float:
        """Maximum allowed total spend per calendar month, in USD."""
        return float(self._config_get("monthly_cap", str(_DEFAULT_MONTHLY_CAP)))

    def budget_remaining(self) -> float:
        """Remaining budget for the current month (may be negative if over)."""
        return self.monthly_cap() - self.monthly_spend()

    def is_over_budget(self) -> bool:
        """True when monthly spend equals or exceeds the monthly cap."""
        return self.monthly_spend() >= self.monthly_cap()

    def set_routing_mode(self, mode: str) -> None:
        """Persist the routing mode. Raises ValueError for unknown modes."""
        if mode not in VALID_ROUTING_MODES:
            raise ValueError(
                f"Unknown routing mode {mode!r}. Valid modes: {sorted(VALID_ROUTING_MODES)}"
            )
        self._config_set("routing_mode", mode)

    def get_routing_mode(self) -> str:
        """Return the current routing mode. Defaults to 'standard'."""
        return self._config_get("routing_mode", _DEFAULT_ROUTING_MODE)

    def reset_monthly_records(self) -> int:
        """Delete all cost records for the current UTC calendar month.

        Returns the number of rows deleted.
        """
        month_prefix = _now().strftime("%Y-%m")
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM cost_records WHERE timestamp LIKE ?",
                (f"{month_prefix}%",),
            )
        return cur.rowcount
