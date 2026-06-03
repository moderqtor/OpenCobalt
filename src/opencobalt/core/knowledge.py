"""SQLite-backed project dependency and decision map."""

from __future__ import annotations

import ast
import sqlite3
import subprocess
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kg_nodes (
    id       TEXT PRIMARY KEY,
    type     TEXT NOT NULL,
    label    TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS kg_edges (
    id       TEXT PRIMARY KEY,
    from_id  TEXT NOT NULL,
    to_id    TEXT NOT NULL,
    rel      TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_kg_nodes_label ON kg_nodes (label);
CREATE INDEX IF NOT EXISTS idx_kg_edges_from ON kg_edges (from_id);
"""


class KnowledgeGraph:
    """Lightweight SQLite-backed graph of files, modules, and decisions."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = (db_path or Path(".opencobalt") / "knowledge.db").expanduser().resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def ingest_git_log(self, n: int = 100) -> int:
        """Parse recent git commits into change nodes. Returns count added."""
        try:
            result = subprocess.run(
                ["git", "log", f"-{n}", "--pretty=format:%H|%s|%ad", "--date=short"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return 0
        except Exception:
            return 0

        added = 0
        with self._connect() as conn:
            for line in result.stdout.splitlines():
                parts = line.split("|", 2)
                if len(parts) < 2:
                    continue
                sha, message = parts[0], parts[1]
                node_id = f"commit:{sha[:8]}"
                existing = conn.execute("SELECT id FROM kg_nodes WHERE id = ?", (node_id,)).fetchone()
                if not existing:
                    conn.execute(
                        "INSERT INTO kg_nodes VALUES (?,?,?,?)",
                        (node_id, "commit", message[:120], "{}"),
                    )
                    added += 1
        return added

    def ingest_imports(self, src_dir: Path) -> int:
        """Parse Python imports and build dependency edges. Returns edge count."""
        edges_added = 0
        py_files = list(src_dir.rglob("*.py"))

        with self._connect() as conn:
            for py_file in py_files:
                label = str(py_file.relative_to(src_dir))
                node_id = f"file:{label}"
                conn.execute(
                    "INSERT OR IGNORE INTO kg_nodes VALUES (?,?,?,?)",
                    (node_id, "file", label, "{}"),
                )

            for py_file in py_files:
                from_label = str(py_file.relative_to(src_dir))
                from_id = f"file:{from_label}"
                try:
                    tree = ast.parse(py_file.read_text(encoding="utf-8", errors="ignore"))
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        mod = node.module.replace(".", "/") + ".py"
                        to_id = f"file:{mod}"
                        edge_id = f"edge:{from_id}:{to_id}"
                        conn.execute(
                            "INSERT OR IGNORE INTO kg_edges VALUES (?,?,?,?,?)",
                            (edge_id, from_id, to_id, "imports", "{}"),
                        )
                        edges_added += 1
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            mod = alias.name.replace(".", "/") + ".py"
                            to_id = f"file:{mod}"
                            edge_id = f"edge:{from_id}:{to_id}"
                            conn.execute(
                                "INSERT OR IGNORE INTO kg_edges VALUES (?,?,?,?,?)",
                                (edge_id, from_id, to_id, "imports", "{}"),
                            )
                            edges_added += 1
        return edges_added

    def query(self, question: str) -> str:
        """Keyword search over node labels."""
        terms = [term.lower() for term in question.split() if len(term) > 2]
        if not terms:
            return "No search terms found."

        with self._connect() as conn:
            results = []
            for term in terms[:3]:
                rows = conn.execute(
                    "SELECT type, label FROM kg_nodes WHERE LOWER(label) LIKE ? LIMIT 10",
                    (f"%{term}%",),
                ).fetchall()
                results.extend(rows)

        if not results:
            return f"No knowledge graph entries found for: {question}"

        seen = set()
        lines = [f"Knowledge graph results for: {question}"]
        for row in results:
            key = f"{row['type']}:{row['label']}"
            if key not in seen:
                seen.add(key)
                lines.append(f"  [{row['type']}] {row['label']}")
        return "\n".join(lines[:15])

    def why(self, file_path: str) -> str:
        """Return a 2-hop dependency trail for a file."""
        node_id = f"file:{file_path}"

        with self._connect() as conn:
            node = conn.execute(
                "SELECT * FROM kg_nodes WHERE id = ? OR label LIKE ?",
                (node_id, f"%{file_path}%"),
            ).fetchone()
            if not node:
                return f"No knowledge graph entry for: {file_path}\nRun: opencobalt /graph ingest"

            importers = conn.execute(
                "SELECT n.label FROM kg_edges e JOIN kg_nodes n ON e.from_id = n.id "
                "WHERE e.to_id LIKE ? AND e.rel = 'imports' LIMIT 10",
                (f"%{file_path}%",),
            ).fetchall()

            imports = conn.execute(
                "SELECT n.label FROM kg_edges e JOIN kg_nodes n ON e.to_id = n.id "
                "WHERE e.from_id LIKE ? AND e.rel = 'imports' LIMIT 10",
                (f"%{file_path}%",),
            ).fetchall()

        lines = [f"Knowledge trail: {file_path}"]
        if importers:
            lines.append(f"\nImported by ({len(importers)}):")
            for row in importers:
                lines.append(f"  <- {row['label']}")
        if imports:
            lines.append(f"\nImports ({len(imports)}):")
            for row in imports:
                lines.append(f"  -> {row['label']}")
        if not importers and not imports:
            lines.append("  No dependency edges found. Run: /graph ingest")
        return "\n".join(lines)
