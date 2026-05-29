"""Memory store: writes and reads MemoryRecord objects via the ledger.

SQLite is the source of truth. Markdown export is a read-only mirror.
"""

from __future__ import annotations

from pathlib import Path

from .ledger import Ledger
from .models import MemoryRecord


class MemoryStore:
    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    def write(
        self,
        project: str,
        namespace: str,
        content: str,
        source: str = "cli",
        metadata: dict | None = None,
    ) -> MemoryRecord:
        record = MemoryRecord(
            project=project,
            namespace=namespace,
            content=content,
            source=source,
            metadata=metadata or {},
        )
        self._ledger.insert_memory_record(record)
        return record

    def read(
        self,
        project: str,
        namespace: str | None = None,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        return self._ledger.list_memory_records(
            project=project,
            namespace=namespace,
            limit=limit,
        )

    def export_markdown(self, project: str, output_path: Path) -> None:
        """Write a markdown mirror of all memory records for a project.

        This file is generated from SQLite and is not the source of truth.
        """
        records = self.read(project)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"# Memory Export: {project}\n"]
        lines.append(f"Records: {len(records)}\n")
        lines.append("---\n")
        for r in records:
            lines.append(f"## [{r.namespace}] {r.timestamp.strftime('%Y-%m-%d %H:%M')}\n")
            lines.append(f"{r.content}\n")
            lines.append(f"*source: {r.source}*\n\n")
        output_path.write_text("".join(lines), encoding="utf-8")
