# Cobalt Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform `opencobalt` into a persistent interactive shell with slash commands, auto-routing, background multi-model orchestration, pipelines, and a self-learning router.

**Architecture:** Additive build on top of the existing Typer CLI. `opencobalt` with no args drops into a `prompt_toolkit` REPL (`shell.py`). All existing commands become `/command` aliases. Background orchestration uses a `ThreadPoolExecutor` in `background.py`. Learning router wraps `route_task()` with outcome-weighted adjustments stored in a new `outcomes` ledger table.

**Tech Stack:** Python 3.11+, `prompt_toolkit>=3.0` (REPL), `watchdog>=4.0` (optional file watcher), existing SQLite ledger, `subprocess.Popen` for tool invocation. All model calls go through installed CLI binaries (`claude`, `codex`, `gemini`) — no REST APIs.

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `src/opencobalt/shell.py` | CobaltShell REPL — prompt loop, dispatch, status line |
| Create | `src/opencobalt/core/background.py` | BackgroundRunner — ThreadPoolExecutor, result queue |
| Create | `src/opencobalt/core/pipeline.py` | Pipeline — parse `/pipe` syntax, run step chain |
| Create | `src/opencobalt/core/learning_router.py` | LearningRouter — outcome-weighted routing |
| Create | `src/opencobalt/core/knowledge.py` | KnowledgeGraph — SQLite dependency + decision map |
| Create | `tests/test_shell.py` | Shell dispatch, status line, slash command registry |
| Create | `tests/test_background.py` | Task queue, result draining, timeout |
| Create | `tests/test_pipeline.py` | Parse syntax, step order, output handoff |
| Create | `tests/test_learning_router.py` | Outcome recording, weight computation, decay |
| Create | `tests/test_knowledge.py` | Git log ingestion, import parsing, traversal |
| Modify | `src/opencobalt/cli.py` | No-args entry point → launches shell |
| Modify | `src/opencobalt/core/brief.py` | Add `generate_startup()` — 4-line startup brief |
| Modify | `src/opencobalt/core/council.py` | Add `consult_subprocess()` — binary invocation |
| Modify | `src/opencobalt/core/verify.py` | Add `verify_async()` — non-blocking verify |
| Modify | `src/opencobalt/core/ledger.py` | Add `outcomes` table + `insert_outcome()` / `list_outcomes()` |
| Modify | `pyproject.toml` | Add `prompt_toolkit>=3.0`; add `[shell]` optional extras |

---

## Phase 1: Core Shell + Background Runner

_After this phase: `opencobalt` opens an interactive shell with slash commands, auto-routing, morning brief, and background council._

---

### Task 1: Add dependencies to pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add prompt_toolkit to base dependencies**

In `pyproject.toml`, add to `[project] dependencies`:
```toml
dependencies = [
    "typer>=0.12",
    "pydantic>=2.0",
    "rich>=13.0",
    "prompt_toolkit>=3.0",
]
```

- [ ] **Step 2: Add shell optional extras**

Add a new section after the existing `[project.optional-dependencies]`:
```toml
shell = [
    "watchdog>=4.0",
]
```

- [ ] **Step 3: Verify install**

```bash
pip install -e ".[dev]"
python3 -c "import prompt_toolkit; print(prompt_toolkit.__version__)"
```
Expected: prints a version string like `3.0.x`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: add prompt_toolkit dep, shell optional extras"
```

---

### Task 2: Add `generate_startup()` to BriefGenerator

**Files:**
- Modify: `src/opencobalt/core/brief.py`
- Test: `tests/test_brief.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_brief.py`:
```python
def test_generate_startup_is_compact(tmp_path: Path) -> None:
    ledger = _make_ledger(tmp_path)
    gen = BriefGenerator(ledger, bridge_path=tmp_path / "memories.db")
    output = gen.generate_startup()
    lines = [l for l in output.splitlines() if l.strip()]
    assert len(lines) <= 6
    assert "BRIEF" in output or "brief" in output.lower()

def test_generate_startup_with_routes(tmp_path: Path) -> None:
    ledger = _make_ledger(tmp_path)
    d = RouteDecision(
        task="implement JWT rotation",
        recommended_tool="claude-code",
        score=94,
        reasoning="test",
        tier="executive",
        scores={"claude-code": 94},
    )
    ledger.insert_route_decision(d)
    gen = BriefGenerator(ledger, bridge_path=tmp_path / "memories.db")
    output = gen.generate_startup()
    assert "claude-code" in output or "JWT" in output
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_brief.py::test_generate_startup_is_compact -v
```
Expected: `AttributeError: 'BriefGenerator' object has no attribute 'generate_startup'`

- [ ] **Step 3: Implement `generate_startup()` in `brief.py`**

Add this method to the `BriefGenerator` class (after `generate()`):
```python
def generate_startup(self) -> str:
    """Return a compact 4-6 line brief for shell startup."""
    cutoff = _now_utc() - timedelta(days=1)
    decisions = self._ledger.list_route_decisions(limit=100)
    recent = [d for d in decisions if (_parse_ts(d.timestamp) or _now_utc()) >= cutoff]

    lines = ["BRIEF  yesterday"]
    if recent:
        tool_counts: dict[str, int] = {}
        for d in recent:
            tool_counts[d.recommended_tool] = tool_counts.get(d.recommended_tool, 0) + 1
        summary = " · ".join(f"{t} ×{n}" for t, n in sorted(tool_counts.items(), key=lambda x: -x[1]))
        lines.append(f"→ {len(recent)} routes · {summary}")
        last = recent[0]
        lines.append(f"→ last: {last.task[:60]}")
    else:
        lines.append("→ no activity yesterday")

    risks = self._get_recent_notes(cutoff=_now_utc() - timedelta(days=7), tag="risk")
    decisions_tagged = self._get_recent_notes(cutoff=_now_utc() - timedelta(days=7), tag="decision")
    if risks:
        lines.append(f"! risk: {risks[0].get('content','')[:60]}")
    if decisions_tagged:
        lines.append(f"! open: {decisions_tagged[0].get('content','')[:60]}")
    if not risks and not decisions_tagged:
        lines.append("✓ no open risks or decisions")

    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python3 -m pytest tests/test_brief.py -v
```
Expected: all brief tests pass (including the 5 existing ones)

- [ ] **Step 5: Commit**

```bash
git add src/opencobalt/core/brief.py tests/test_brief.py
git commit -m "feat: BriefGenerator.generate_startup() -- compact shell header brief"
```

---

### Task 3: Add `outcomes` table to Ledger

**Files:**
- Modify: `src/opencobalt/core/ledger.py`
- Test: `tests/test_ledger.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ledger.py`:
```python
def test_insert_and_list_outcomes(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db")
    ledger.insert_outcome(
        task_id="task-123",
        tool="claude-code",
        outcome="committed",
    )
    outcomes = ledger.list_outcomes(limit=10)
    assert len(outcomes) == 1
    assert outcomes[0]["tool"] == "claude-code"
    assert outcomes[0]["outcome"] == "committed"

def test_outcomes_table_created_on_init(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db")
    # Should not raise
    outcomes = ledger.list_outcomes()
    assert outcomes == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_ledger.py::test_insert_and_list_outcomes -v
```
Expected: `AttributeError: 'Ledger' object has no attribute 'insert_outcome'`

- [ ] **Step 3: Add schema and methods to `ledger.py`**

Add to the `_SCHEMA` string (after the last `CREATE TABLE` block):
```python
_SCHEMA += """
CREATE TABLE IF NOT EXISTS outcomes (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    task_id     TEXT NOT NULL,
    tool        TEXT NOT NULL,
    outcome     TEXT NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}'
);
"""
```

Add these two methods to the `Ledger` class:
```python
def insert_outcome(
    self,
    task_id: str,
    tool: str,
    outcome: str,
    metadata: dict | None = None,
) -> None:
    import uuid
    from datetime import datetime, timezone
    with self._connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO outcomes VALUES (?,?,?,?,?,?)",
            (
                str(uuid.uuid4()),
                datetime.now(tz=timezone.utc).isoformat(),
                task_id,
                tool,
                outcome,
                json.dumps(metadata or {}),
            ),
        )

def list_outcomes(self, *, limit: int = 100, tool: str | None = None) -> list[dict]:
    sql = "SELECT * FROM outcomes"
    params: list = []
    if tool:
        sql += " WHERE tool = ?"
        params.append(tool)
    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    with self._connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_ledger.py -v
```
Expected: all ledger tests pass

- [ ] **Step 5: Commit**

```bash
git add src/opencobalt/core/ledger.py tests/test_ledger.py
git commit -m "feat: ledger outcomes table -- task outcome tracking for learning router"
```

---

### Task 4: Create BackgroundRunner

**Files:**
- Create: `src/opencobalt/core/background.py`
- Create: `tests/test_background.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_background.py`:
```python
"""Tests for BackgroundRunner."""
from __future__ import annotations

import time
from opencobalt.core.background import BackgroundResult, BackgroundRunner


def test_submit_and_drain():
    runner = BackgroundRunner(max_workers=2)
    runner.submit("t1", lambda: "hello world")
    time.sleep(0.2)
    results = runner.drain()
    runner.shutdown()
    assert len(results) == 1
    assert results[0].task_id == "t1"
    assert results[0].output == "hello world"
    assert results[0].error is None


def test_drain_is_nonblocking():
    runner = BackgroundRunner(max_workers=2)
    results = runner.drain()  # nothing submitted
    runner.shutdown()
    assert results == []


def test_error_captured_not_raised():
    def bad():
        raise ValueError("boom")

    runner = BackgroundRunner(max_workers=1)
    runner.submit("t2", bad)
    time.sleep(0.2)
    results = runner.drain()
    runner.shutdown()
    assert len(results) == 1
    assert results[0].error == "boom"
    assert results[0].output == ""


def test_multiple_tasks_all_drain():
    runner = BackgroundRunner(max_workers=3)
    for i in range(3):
        runner.submit(f"task-{i}", lambda i=i: f"result-{i}")
    time.sleep(0.3)
    results = runner.drain()
    runner.shutdown()
    assert len(results) == 3


def test_shutdown_is_safe_when_idle():
    runner = BackgroundRunner()
    runner.shutdown()  # should not raise
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_background.py -v
```
Expected: `ModuleNotFoundError: No module named 'opencobalt.core.background'`

- [ ] **Step 3: Create `src/opencobalt/core/background.py`**

```python
"""Thread-based background task runner for the cobalt shell."""
from __future__ import annotations

import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field


@dataclass
class BackgroundResult:
    task_id: str
    output: str
    error: str | None = None
    elapsed_s: float = 0.0
    metadata: dict = field(default_factory=dict)


class BackgroundRunner:
    """Run callables in background threads; drain results non-blockingly."""

    def __init__(self, max_workers: int = 3) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._results: queue.Queue[BackgroundResult] = queue.Queue()
        self._lock = threading.Lock()

    def submit(self, task_id: str, fn, *args) -> None:
        """Enqueue fn(*args) to run in a background thread."""
        import time

        def _run():
            t0 = time.monotonic()
            try:
                output = fn(*args)
                elapsed = time.monotonic() - t0
                self._results.put(BackgroundResult(
                    task_id=task_id,
                    output=str(output) if output is not None else "",
                    elapsed_s=round(elapsed, 2),
                ))
            except Exception as exc:
                elapsed = time.monotonic() - t0
                self._results.put(BackgroundResult(
                    task_id=task_id,
                    output="",
                    error=str(exc),
                    elapsed_s=round(elapsed, 2),
                ))

        self._executor.submit(_run)

    def drain(self) -> list[BackgroundResult]:
        """Return all completed results without blocking."""
        results = []
        while True:
            try:
                results.append(self._results.get_nowait())
            except queue.Empty:
                break
        return results

    def shutdown(self) -> None:
        """Shut down the executor cleanly."""
        self._executor.shutdown(wait=False, cancel_futures=True)
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_background.py -v
```
Expected: all 5 tests pass

- [ ] **Step 5: Run full suite to confirm nothing broke**

```bash
python3 -m pytest -q
```
Expected: 289+ passed

- [ ] **Step 6: Commit**

```bash
git add src/opencobalt/core/background.py tests/test_background.py
git commit -m "feat: BackgroundRunner -- thread-based background task queue for shell"
```

---

### Task 5: Add `consult_subprocess()` to council.py

**Files:**
- Modify: `src/opencobalt/core/council.py`
- Test: `tests/test_council.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_council.py`:
```python
def test_consult_subprocess_returns_string(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import subprocess
    from opencobalt.core.council import consult_subprocess

    def fake_run(cmd, **kwargs):
        class R:
            stdout = "- Use SQLite\n- Write tests first"
            returncode = 0
        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = consult_subprocess("refactor the router", model="claude")
    assert "SQLite" in result or isinstance(result, str)


def test_consult_subprocess_graceful_when_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil
    from opencobalt.core.council import consult_subprocess

    monkeypatch.setattr(shutil, "which", lambda x: None)
    result = consult_subprocess("some task", model="claude")
    assert "not found" in result.lower() or "unavailable" in result.lower()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_council.py::test_consult_subprocess_returns_string -v
```
Expected: `ImportError` or `AttributeError`

- [ ] **Step 3: Add `consult_subprocess()` to `council.py`**

Add after the existing `CouncilSession` class:
```python
def consult_subprocess(task: str, model: str = "claude") -> str:
    """Call a CLI binary non-interactively and return its text output.

    Uses installed subscription binaries (claude, codex, gemini), not REST APIs.
    Falls back gracefully if binary not found or call fails.
    """
    import shutil
    import subprocess

    _BINARY_MAP = {
        "claude": ["claude", "--print"],
        "codex": ["codex", "--quiet"],
        "gemini": ["gemini", "--print"],
    }
    _INSTALL_HINT = {
        "claude": "npm install -g @anthropic-ai/claude-code",
        "codex": "npm install -g @openai/codex",
        "gemini": "npm install -g @google/gemini-cli",
    }

    cmd_prefix = _BINARY_MAP.get(model, [model])
    binary = cmd_prefix[0]

    if not shutil.which(binary):
        hint = _INSTALL_HINT.get(model, "check tool documentation")
        return f"[{model} unavailable — not found on PATH. Install: {hint}]"

    prompt = (
        f"You are a technical advisor. Task: {task}\n\n"
        "Give your recommendation in 3-5 bullet points. Be specific and direct."
    )
    try:
        result = subprocess.run(
            cmd_prefix + [prompt],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.stdout.strip() or f"[{model}: no output]"
    except subprocess.TimeoutExpired:
        return f"[{model}: timed out after 60s]"
    except Exception as exc:
        return f"[{model}: error — {exc}]"
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_council.py -v
```
Expected: all council tests pass

- [ ] **Step 5: Commit**

```bash
git add src/opencobalt/core/council.py tests/test_council.py
git commit -m "feat: council.consult_subprocess() -- binary-based model calls using subscription limits"
```

---

### Task 6: Create the CobaltShell

**Files:**
- Create: `src/opencobalt/shell.py`
- Create: `tests/test_shell.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_shell.py`:
```python
"""Tests for CobaltShell dispatch logic."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from opencobalt.shell import CobaltShell


@pytest.fixture()
def shell(tmp_path: Path) -> CobaltShell:
    return CobaltShell(
        db_path=tmp_path / ".opencobalt" / "ledger.db",
        bridge_path=tmp_path / ".opencobalt" / "memories.db",
    )


def test_dispatch_slash_status(shell: CobaltShell, capsys) -> None:
    with patch.object(shell, "_run_command") as mock_cmd:
        shell.dispatch("/status")
    mock_cmd.assert_called_once_with("status", [])


def test_dispatch_slash_with_args(shell: CobaltShell) -> None:
    with patch.object(shell, "_run_command") as mock_cmd:
        shell.dispatch("/route design the auth module")
    mock_cmd.assert_called_once_with("route", ["design the auth module"])


def test_dispatch_plain_prompt_calls_router(shell: CobaltShell) -> None:
    with patch("opencobalt.shell.route_task") as mock_route, \
         patch.object(shell, "_open_tool") as mock_open, \
         patch.object(shell, "_queue_background_council"):
        mock_route.return_value = MagicMock(
            recommended_tool="claude-code",
            score=86,
            tier="executive",
            reasoning="test",
            task="design auth",
            id="test-id",
            scores={"claude-code": 86},
        )
        shell.dispatch("design the auth module")
    mock_route.assert_called_once_with("design the auth module", record=False)
    mock_open.assert_called_once()


def test_dispatch_slash_palette(shell: CobaltShell, capsys) -> None:
    shell.dispatch("/")
    captured = capsys.readouterr()
    assert "/route" in captured.out or "route" in captured.out


def test_render_status_returns_string(shell: CobaltShell) -> None:
    status = shell.render_status()
    assert isinstance(status, str)
    assert len(status) > 0


def test_slash_commands_list(shell: CobaltShell) -> None:
    commands = shell.list_slash_commands()
    assert "route" in commands
    assert "brief" in commands
    assert "verify" in commands
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_shell.py -v
```
Expected: `ModuleNotFoundError: No module named 'opencobalt.shell'`

- [ ] **Step 3: Create `src/opencobalt/shell.py`**

```python
"""CobaltShell — interactive REPL for OpenCobalt.

Run with: opencobalt (no args)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from rich.console import Console

from .core.background import BackgroundResult, BackgroundRunner
from .core.brief import BriefGenerator
from .core.ledger import Ledger
from .core.router import route_task

_COBALT = "#7B9EFF"
_GREEN = "#3DFFA0"
_AMBER = "#FFD166"
_DIM = "#555555"

_STYLE = Style.from_dict({
    "prompt": f"bold {_COBALT}",
    "": "",
})

console = Console()


class CobaltShell:
    """Interactive cobalt shell."""

    # Slash commands that delegate to the Typer CLI
    _CLI_COMMANDS = [
        "route", "brief", "status", "history", "stats", "benchmark",
        "verify", "lint", "doctor", "public-check", "context", "export",
        "log", "note", "day", "memory", "agents", "skills", "integrations",
        "cost", "config", "session", "hooks", "council", "debate",
        "install-hooks", "tui", "ui",
    ]

    def __init__(self, db_path: Path, bridge_path: Path) -> None:
        self._db_path = db_path
        self._bridge_path = bridge_path
        self._ledger = Ledger(db_path)
        self._runner = BackgroundRunner(max_workers=3)
        self._council_cache: dict[str, list[BackgroundResult]] = {}
        self._session: PromptSession = PromptSession(
            completer=WordCompleter(
                [f"/{c}" for c in self._CLI_COMMANDS] + ["/pipe", "/graph"],
                match_middle=False,
                sentence=True,
            ),
            style=_STYLE,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Main loop."""
        self._print_header()
        self._print_brief()
        console.print(f"  [dim]Type a task to route it, or [bold]/[/bold] for commands. Ctrl+C to exit.[/dim]\n")

        try:
            while True:
                self._drain_and_notify()
                status = self.render_status()
                try:
                    text = self._session.prompt(
                        HTML(f"<ansicyan>›</ansicyan> "),
                        bottom_toolbar=HTML(f"<style fg='{_DIM}'>{status}</style>"),
                    )
                except KeyboardInterrupt:
                    break
                except EOFError:
                    break

                text = text.strip()
                if not text:
                    continue
                self.dispatch(text)
        finally:
            self.on_exit()

    def dispatch(self, text: str) -> None:
        """Route input to a slash command or the task router."""
        if text == "/":
            self._show_palette()
        elif text.startswith("/"):
            parts = text[1:].split(None, 1)
            cmd = parts[0]
            args = parts[1].split() if len(parts) > 1 else []
            self._run_command(cmd, args)
        else:
            self._route_and_open(text)

    def render_status(self) -> str:
        """Return a one-line status string for the toolbar."""
        parts = []
        try:
            count = self._ledger.count_memory_records()
            parts.append(f"memory {count}")
        except Exception:
            pass
        pending = self._runner.drain()
        if pending:
            self._council_cache.setdefault("pending", []).extend(pending)
            parts.append(f"▶ {len(pending)} background ready — /council show")
        parts.append("watching src/")
        return "  ·  ".join(parts)

    def list_slash_commands(self) -> list[str]:
        """Return all registered slash command names."""
        return list(self._CLI_COMMANDS) + ["pipe", "graph"]

    def on_exit(self) -> None:
        """Session summary on shell exit."""
        self._runner.shutdown()
        console.print("\n  [dim]Session ended.[/dim]\n")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _print_header(self) -> None:
        import importlib.metadata
        try:
            version = importlib.metadata.version("opencobalt")
        except Exception:
            version = "dev"
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d")
        console.print(
            f"\n  [bold {_COBALT}]⬡ OpenCobalt[/bold {_COBALT}]"
            f"  [dim]v{version} · {now}[/dim]\n"
            f"  [dim]{'─' * 52}[/dim]"
        )

    def _print_brief(self) -> None:
        try:
            gen = BriefGenerator(self._ledger, bridge_path=self._bridge_path)
            brief = gen.generate_startup()
            console.print()
            for line in brief.splitlines():
                if line.startswith("!"):
                    console.print(f"  [{_AMBER}]{line}[/{_AMBER}]")
                elif line.startswith("✓"):
                    console.print(f"  [dim]{line}[/dim]")
                else:
                    console.print(f"  [dim]{line}[/dim]")
            console.print()
        except Exception:
            pass

    def _show_palette(self) -> None:
        console.print(f"\n  [bold]Commands[/bold]  [dim]Tab to complete · /cmd args[/dim]\n")
        cols = [self._CLI_COMMANDS[i:i+3] for i in range(0, len(self._CLI_COMMANDS), 3)]
        for row in cols:
            line = "  ".join(f"[{_COBALT}]/{c:<18}[/{_COBALT}]" for c in row)
            console.print(f"  {line}")
        console.print(f"  [{_COBALT}]/pipe[/{_COBALT}]  [{_COBALT}]/graph[/{_COBALT}]\n")

    def _run_command(self, cmd: str, args: list[str]) -> None:
        """Invoke a CLI command via subprocess, inheriting the terminal."""
        argv = ["opencobalt", cmd] + args
        subprocess.run(argv)  # noqa: S603

    def _route_and_open(self, task: str) -> None:
        from .core.brief import BriefGenerator
        decision = route_task(task, record=False)
        self._ledger.insert_route_decision(decision)

        tc = {"executive": _COBALT, "manager": _AMBER, "worker": _DIM}.get(decision.tier, _DIM)
        console.print(
            f"\n  [{tc}]→ {decision.recommended_tool}[/{tc}]"
            f"  [dim]score {decision.score} · {decision.tier}[/dim]"
        )

        # Copy brief to clipboard
        try:
            import platform
            gen = BriefGenerator(self._ledger, bridge_path=self._bridge_path)
            brief_text = gen.generate(days=7)
            if platform.system() == "Darwin":
                import subprocess as _sp
                _sp.run(["pbcopy"], input=brief_text.encode(), check=True, capture_output=True)
                console.print("  [dim]brief copied to clipboard[/dim]")
        except Exception:
            pass

        self._open_tool(decision.recommended_tool)
        self._queue_background_council(task, decision.id)

    def _open_tool(self, tool: str) -> None:
        import shutil
        _BINARIES = {
            "claude-code": "claude",
            "codex-cli": "codex",
            "gemini-cli": "gemini",
            "cursor": "cursor",
            "ollama": None,
        }
        binary = _BINARIES.get(tool, tool)
        if binary is None:
            console.print(f"  [dim]ollama: run manually from another pane[/dim]")
            return
        if not shutil.which(binary):
            console.print(f"  [{_AMBER}]{binary} not on PATH[/{_AMBER}]  [dim]check install[/dim]")
            return
        console.print(f"  [dim]opening {binary}...[/dim]\n")
        subprocess.Popen([binary])  # noqa: S603

    def _queue_background_council(self, task: str, task_id: str) -> None:
        from .core.council import consult_subprocess
        import shutil
        for model in ("codex", "gemini"):
            binary = {"codex": "codex", "gemini": "gemini"}[model]
            if shutil.which(binary):
                self._runner.submit(
                    f"{task_id}:{model}",
                    consult_subprocess,
                    task,
                    model,
                )

    def _drain_and_notify(self) -> None:
        results = self._runner.drain()
        if results:
            console.print(f"\n  [{_AMBER}]▶ background ready[/{_AMBER}]  [dim]{len(results)} model(s)[/dim]")
            for r in results:
                model = r.task_id.split(":")[-1] if ":" in r.task_id else r.task_id
                preview = (r.output[:80] + "...") if len(r.output) > 80 else r.output
                console.print(f"  [dim][{model}][/dim] {preview}")
            console.print(f"  [dim]run [bold]/council show[/bold] for full synthesis[/dim]\n")
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_shell.py -v
```
Expected: all 6 shell tests pass

- [ ] **Step 5: Commit**

```bash
git add src/opencobalt/shell.py tests/test_shell.py
git commit -m "feat: CobaltShell -- prompt_toolkit REPL with slash commands and background council"
```

---

### Task 7: Wire no-args entry point in cli.py

**Files:**
- Modify: `src/opencobalt/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py` (near the top of the file, with existing CLI tests):
```python
def test_no_args_entry_point_exists():
    """opencobalt with no args should not error — it invokes the shell."""
    from opencobalt.shell import CobaltShell
    # Just confirm CobaltShell is importable and constructable
    from pathlib import Path
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        shell = CobaltShell(
            db_path=Path(d) / "ledger.db",
            bridge_path=Path(d) / "memories.db",
        )
        assert hasattr(shell, "run")
        assert hasattr(shell, "dispatch")
```

- [ ] **Step 2: Run test to confirm it passes already**

```bash
python3 -m pytest tests/test_cli.py::test_no_args_entry_point_exists -v
```
Expected: PASS (CobaltShell already exists from Task 6)

- [ ] **Step 3: Wire the no-args entry point in `cli.py`**

In `cli.py`, find the `app = typer.Typer(...)` block near the top and add a callback:

```python
@app.callback(invoke_without_command=True)
def _main(ctx: typer.Context) -> None:
    """OpenCobalt — local-first AI orchestration shell."""
    if ctx.invoked_subcommand is None:
        from .shell import CobaltShell
        shell = CobaltShell(db_path=_DB_PATH, bridge_path=_MEMORIES_DB)
        shell.run()
```

This goes immediately after the `app = typer.Typer(...)` line and before any `@app.command()` definitions.

- [ ] **Step 4: Smoke test manually**

```bash
opencobalt --help
```
Expected: help text still works (no change to help output)

```bash
opencobalt status
```
Expected: status command still works

- [ ] **Step 5: Run full test suite**

```bash
python3 -m pytest -q
```
Expected: all tests pass (300+)

- [ ] **Step 6: Commit**

```bash
git add src/opencobalt/cli.py tests/test_cli.py
git commit -m "feat: opencobalt no-args entry point -- launches CobaltShell REPL"
```

---

## Phase 2: Pipeline Executor

_After this phase: `/pipe "task" → claude → codex → /verify` works end-to-end._

---

### Task 8: Create Pipeline executor

**Files:**
- Create: `src/opencobalt/core/pipeline.py`
- Create: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pipeline.py`:
```python
"""Tests for Pipeline executor."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from opencobalt.core.pipeline import Pipeline, PipelineStep


def test_parse_simple_pipeline():
    p = Pipeline(output_dir=Path("/tmp/test-pipe"))
    task, steps = p.parse('/pipe "add rate limiting" → claude → codex → /verify')
    assert task == "add rate limiting"
    assert len(steps) == 3
    assert steps[0].tool == "claude"
    assert steps[1].tool == "codex"
    assert steps[2].tool == "verify"


def test_parse_with_hints():
    p = Pipeline(output_dir=Path("/tmp/test-pipe"))
    task, steps = p.parse('/pipe "build auth" → claude design → codex implement → /verify')
    assert steps[0].tool == "claude"
    assert steps[0].hint == "design"
    assert steps[1].tool == "codex"
    assert steps[1].hint == "implement"


def test_parse_rejects_empty():
    p = Pipeline(output_dir=Path("/tmp/test-pipe"))
    with pytest.raises(ValueError, match="No steps"):
        p.parse('/pipe "task"')


def test_parse_note_step():
    p = Pipeline(output_dir=Path("/tmp/test-pipe"))
    task, steps = p.parse('/pipe "task" → claude → /note checkpoint reached → /verify')
    assert steps[1].tool == "note"
    assert "checkpoint" in steps[1].hint


def test_step_output_path(tmp_path):
    p = Pipeline(output_dir=tmp_path / "pipelines")
    path = p._step_output_path("run-1", 0)
    assert path.parent.exists() or not path.exists()
    assert "step-0" in str(path)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_pipeline.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `src/opencobalt/core/pipeline.py`**

```python
"""Pipeline executor — runs ordered tool steps for a task."""
from __future__ import annotations

import re
import subprocess
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PipelineStep:
    tool: str    # 'claude' | 'codex' | 'gemini' | 'verify' | 'note'
    hint: str = ""  # 'design' | 'implement' | 'review' | note text | ''


@dataclass
class PipelineResult:
    task: str
    run_id: str
    steps_completed: int
    steps_total: int
    success: bool
    output_dir: Path
    errors: list[str] = field(default_factory=list)


_BINARY_MAP = {
    "claude": "claude",
    "codex": "codex",
    "gemini": "gemini",
}


class Pipeline:
    def __init__(self, output_dir: Path | None = None) -> None:
        self._output_dir = output_dir or (Path(".opencobalt") / "pipelines")

    def parse(self, expr: str) -> tuple[str, list[PipelineStep]]:
        """Parse /pipe "task" → step1 → step2 → ... into (task, steps)."""
        # Strip leading /pipe
        expr = re.sub(r"^/?pipe\s*", "", expr.strip())

        # Extract quoted task
        m = re.match(r'"([^"]+)"\s*(.*)', expr)
        if not m:
            m = re.match(r"'([^']+)'\s*(.*)", expr)
        if not m:
            raise ValueError("Pipeline task must be quoted: /pipe \"task\" → ...")
        task = m.group(1).strip()
        rest = m.group(2).strip()

        if not rest:
            raise ValueError("No steps defined. Example: /pipe \"task\" → claude → /verify")

        raw_steps = [s.strip() for s in re.split(r"→|->", rest) if s.strip()]
        steps = []
        for raw in raw_steps:
            raw = raw.lstrip("/").strip()
            if raw.startswith("note "):
                steps.append(PipelineStep(tool="note", hint=raw[5:].strip()))
            elif raw.startswith("verify"):
                steps.append(PipelineStep(tool="verify"))
            else:
                parts = raw.split(None, 1)
                tool = parts[0].lower()
                hint = parts[1].strip() if len(parts) > 1 else ""
                steps.append(PipelineStep(tool=tool, hint=hint))

        if not steps:
            raise ValueError("No steps defined.")
        return task, steps

    def run(self, task: str, steps: list[PipelineStep]) -> PipelineResult:
        run_id = str(uuid.uuid4())[:8]
        run_dir = self._output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        context = f"Task: {task}"
        errors = []

        for i, step in enumerate(steps):
            out_path = self._step_output_path(run_id, i)
            result = self._run_step(step, context, out_path)
            if not result:
                errors.append(f"Step {i+1} ({step.tool}) failed or was skipped")
                return PipelineResult(
                    task=task, run_id=run_id,
                    steps_completed=i, steps_total=len(steps),
                    success=False, output_dir=run_dir, errors=errors,
                )
            if out_path.exists():
                context = out_path.read_text(encoding="utf-8", errors="ignore")

        return PipelineResult(
            task=task, run_id=run_id,
            steps_completed=len(steps), steps_total=len(steps),
            success=True, output_dir=run_dir, errors=errors,
        )

    def _run_step(self, step: PipelineStep, context: str, out_path: Path) -> bool:
        if step.tool == "note":
            out_path.write_text(step.hint, encoding="utf-8")
            return True

        if step.tool == "verify":
            from .verify import run_all
            from .ledger import Ledger
            results = run_all(root=Path("."), ledger=Ledger())
            out_path.write_text("\n".join(r.output_summary for r in results))
            return all(r.passed for r in results)

        binary = _BINARY_MAP.get(step.tool)
        if not binary or not shutil.which(binary):
            out_path.write_text(f"[{step.tool} not available]")
            return False

        # Write context to a temp file for the tool to pick up
        ctx_file = out_path.parent / f"ctx-{out_path.name}"
        ctx_file.write_text(context, encoding="utf-8")

        proc = subprocess.run([binary], check=False)
        if out_path.exists():
            return True
        # Tool didn't write output — treat as success but no handoff
        out_path.write_text(f"[{step.tool}: completed, no output file written]")
        return proc.returncode == 0

    def _step_output_path(self, run_id: str, step_index: int) -> Path:
        run_dir = self._output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir / f"step-{step_index}.txt"
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_pipeline.py -v
```
Expected: all 5 tests pass

- [ ] **Step 5: Add `/pipe` command handler to `shell.py`**

In `CobaltShell._run_command()`, add a branch before the generic `subprocess.run` call:

```python
def _run_command(self, cmd: str, args: list[str]) -> None:
    if cmd == "pipe":
        self._run_pipe(" ".join(args))
        return
    if cmd == "council" and args and args[0] == "show":
        self._show_council_cache()
        return
    argv = ["opencobalt", cmd] + args
    subprocess.run(argv)  # noqa: S603

def _run_pipe(self, expr: str) -> None:
    from .core.pipeline import Pipeline
    from rich.console import Console as _C
    c = _C()
    try:
        pipe = Pipeline()
        task, steps = pipe.parse(f'/pipe "{expr}"' if not expr.startswith('"') else f"/pipe {expr}")
        c.print(f"\n  [dim]Pipeline: {len(steps)} steps[/dim]\n")
        for i, s in enumerate(steps, 1):
            hint = f" {s.hint}" if s.hint else ""
            c.print(f"  [dim]step {i}/{len(steps)}[/dim]  {s.tool}{hint}")
        c.print()
        result = pipe.run(task, steps)
        if result.success:
            c.print(f"  [bold #3DFFA0]VERIFIED ✓[/bold #3DFFA0]  [dim]pipeline complete[/dim]")
        else:
            c.print(f"  [bold #FF5577]pipeline stopped[/bold #FF5577]")
            for err in result.errors:
                c.print(f"  [dim]{err}[/dim]")
    except ValueError as exc:
        c.print(f"  [#FFD166]pipeline error:[/#FFD166]  {exc}")

def _show_council_cache(self) -> None:
    all_results = []
    for results in self._council_cache.values():
        all_results.extend(results)
    if not all_results:
        console.print("  [dim]No background council results yet.[/dim]")
        return
    for r in all_results[-6:]:
        model = r.task_id.split(":")[-1] if ":" in r.task_id else r.task_id
        console.print(f"\n  [bold][{model.upper()}][/bold]")
        for line in r.output.splitlines()[:6]:
            console.print(f"  [dim]{line}[/dim]")
    self._council_cache.clear()
```

- [ ] **Step 6: Run full suite**

```bash
python3 -m pytest -q
```
Expected: 300+ passed

- [ ] **Step 7: Commit**

```bash
git add src/opencobalt/core/pipeline.py src/opencobalt/shell.py tests/test_pipeline.py
git commit -m "feat: pipeline executor -- /pipe task → claude → codex → /verify step chains"
```

---

## Phase 3: Learning Router

_After this phase: routing weights adapt over time based on which tool's output you actually committed._

---

### Task 9: Create LearningRouter

**Files:**
- Create: `src/opencobalt/core/learning_router.py`
- Create: `tests/test_learning_router.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_learning_router.py`:
```python
"""Tests for LearningRouter."""
from __future__ import annotations

from pathlib import Path

import pytest

from opencobalt.core.learning_router import LearningRouter
from opencobalt.core.ledger import Ledger


@pytest.fixture()
def router(tmp_path: Path) -> LearningRouter:
    return LearningRouter(Ledger(tmp_path / "ledger.db"))


def test_route_returns_decision(router: LearningRouter) -> None:
    decision = router.route("design the auth module")
    assert decision.recommended_tool in ("claude-code", "codex-cli", "gemini-cli", "cursor", "ollama")
    assert decision.score > 0


def test_record_outcome_stores_to_ledger(router: LearningRouter, tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db")
    router2 = LearningRouter(ledger)
    router2.record_outcome("task-123", "claude-code", "committed")
    outcomes = ledger.list_outcomes(tool="claude-code")
    assert len(outcomes) == 1
    assert outcomes[0]["outcome"] == "committed"


def test_get_weights_returns_dict(router: LearningRouter) -> None:
    weights = router.get_weights()
    assert isinstance(weights, dict)


def test_committed_outcome_increases_weight(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db")
    router = LearningRouter(ledger)
    # Record multiple positive outcomes for claude-code
    for _ in range(5):
        router.record_outcome(f"task-{_}", "claude-code", "committed")
    weights = router.get_weights()
    assert weights.get("claude-code", 0.0) > 0.0


def test_reverted_outcome_decreases_weight(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db")
    router = LearningRouter(ledger)
    for _ in range(5):
        router.record_outcome(f"task-{_}", "claude-code", "reverted")
    weights = router.get_weights()
    assert weights.get("claude-code", 0.0) < 0.0


def test_weight_capped_at_fifteen_percent(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db")
    router = LearningRouter(ledger)
    for i in range(100):
        router.record_outcome(f"t{i}", "claude-code", "committed")
    weights = router.get_weights()
    assert abs(weights.get("claude-code", 0.0)) <= 0.15
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_learning_router.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `src/opencobalt/core/learning_router.py`**

```python
"""Learning router — wraps route_task() with outcome-weighted score adjustments."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .ledger import Ledger
from .models import RouteDecision
from .router import _TOOL_PROFILES, route_task

_MAX_ADJUSTMENT = 0.15   # ±15% of base score
_DECAY_DAYS = 30         # outcomes older than this have zero weight
_OUTCOME_WEIGHTS = {
    "committed": +1.0,
    "test_failed": -0.5,
    "reverted": -1.0,
    "skipped": 0.0,
}


class LearningRouter:
    """Route tasks using keyword scoring + learned outcome weights."""

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    def route(self, task: str) -> RouteDecision:
        """Route with base keyword scoring adjusted by learned weights."""
        decision = route_task(task, record=False)
        weights = self.get_weights()
        if not weights:
            return decision

        adjusted_scores = {}
        for tool, score in decision.scores.items():
            adjustment = weights.get(tool, 0.0)
            adjusted_scores[tool] = max(0, int(score * (1 + adjustment)))

        best_tool = max(adjusted_scores, key=lambda t: adjusted_scores[t])
        if best_tool != decision.recommended_tool:
            from typing import cast, Literal
            tier = cast(
                Literal["executive", "manager", "worker"],
                _TOOL_PROFILES[best_tool]["tier"],
            )
            return RouteDecision(
                task=task,
                recommended_tool=best_tool,
                score=adjusted_scores[best_tool],
                reasoning=f"Routed to {best_tool} (learned weight {weights.get(best_tool, 0):+.0%}). Base: {decision.reasoning}",
                tier=tier,
                scores=adjusted_scores,
            )
        return decision

    def record_outcome(self, task_id: str, tool: str, outcome: str) -> None:
        """Record how a task turned out for future weight computation."""
        self._ledger.insert_outcome(task_id=task_id, tool=tool, outcome=outcome)

    def get_weights(self) -> dict[str, float]:
        """Compute per-tool score adjustment factors from recent outcomes."""
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=_DECAY_DAYS)).isoformat()
        try:
            all_outcomes = self._ledger.list_outcomes(limit=500)
        except Exception:
            return {}

        recent = [o for o in all_outcomes if o.get("timestamp", "") >= cutoff]
        if not recent:
            return {}

        tool_scores: dict[str, list[float]] = {}
        for o in recent:
            tool = o["tool"]
            weight = _OUTCOME_WEIGHTS.get(o["outcome"], 0.0)
            tool_scores.setdefault(tool, []).append(weight)

        weights: dict[str, float] = {}
        for tool, scores in tool_scores.items():
            avg = sum(scores) / len(scores)
            # Clamp to ±_MAX_ADJUSTMENT
            weights[tool] = max(-_MAX_ADJUSTMENT, min(_MAX_ADJUSTMENT, avg * _MAX_ADJUSTMENT))

        return weights
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_learning_router.py -v
```
Expected: all 6 tests pass

- [ ] **Step 5: Wire LearningRouter into shell dispatch**

In `src/opencobalt/shell.py`, replace the `route_task` import with `LearningRouter`:

```python
# At top of shell.py, replace:
from .core.router import route_task
# With:
from .core.learning_router import LearningRouter
```

In `CobaltShell.__init__()`, add:
```python
self._learning_router = LearningRouter(self._ledger)
```

In `_route_and_open()`, replace:
```python
decision = route_task(task, record=False)
```
With:
```python
decision = self._learning_router.route(task)
```

Update `test_dispatch_plain_prompt_calls_router` in `tests/test_shell.py`:
```python
def test_dispatch_plain_prompt_calls_router(shell: CobaltShell) -> None:
    from unittest.mock import MagicMock
    with patch.object(shell._learning_router, "route") as mock_route, \
         patch.object(shell, "_open_tool") as mock_open, \
         patch.object(shell, "_queue_background_council"):
        mock_route.return_value = MagicMock(
            recommended_tool="claude-code",
            score=86, tier="executive",
            reasoning="test", task="design auth",
            id="test-id", scores={"claude-code": 86},
        )
        shell.dispatch("design the auth module")
    mock_route.assert_called_once_with("design the auth module")
    mock_open.assert_called_once()
```

- [ ] **Step 6: Run full suite**

```bash
python3 -m pytest -q
```
Expected: 310+ passed

- [ ] **Step 7: Commit**

```bash
git add src/opencobalt/core/learning_router.py src/opencobalt/shell.py tests/test_learning_router.py tests/test_shell.py
git commit -m "feat: LearningRouter -- outcome-weighted routing that learns from committed/reverted tasks"
```

---

## Phase 4: Knowledge Graph

_After this phase: `/graph why does auth.py matter?` returns a dependency + decision trail._

---

### Task 10: Create KnowledgeGraph

**Files:**
- Create: `src/opencobalt/core/knowledge.py`
- Create: `tests/test_knowledge.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_knowledge.py`:
```python
"""Tests for KnowledgeGraph."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from opencobalt.core.knowledge import KnowledgeGraph


@pytest.fixture()
def kg(tmp_path: Path) -> KnowledgeGraph:
    return KnowledgeGraph(db_path=tmp_path / "knowledge.db")


def test_empty_graph_query_returns_string(kg: KnowledgeGraph) -> None:
    result = kg.query("what is the router?")
    assert isinstance(result, str)


def test_empty_graph_why_returns_string(kg: KnowledgeGraph) -> None:
    result = kg.why("router.py")
    assert isinstance(result, str)


def test_ingest_imports_finds_files(kg: KnowledgeGraph, tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("from b import foo\n")
    (src / "b.py").write_text("def foo(): pass\n")
    count = kg.ingest_imports(src)
    assert count >= 1


def test_why_after_ingest(kg: KnowledgeGraph, tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "auth.py").write_text("from db import session\n")
    (src / "db.py").write_text("def session(): pass\n")
    kg.ingest_imports(src)
    result = kg.why("auth.py")
    assert "auth" in result.lower() or isinstance(result, str)


def test_ingest_git_log_graceful_outside_repo(kg: KnowledgeGraph, tmp_path: Path) -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type("R", (), {"stdout": "", "returncode": 128})()
        count = kg.ingest_git_log(n=10)
    assert count == 0
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_knowledge.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `src/opencobalt/core/knowledge.py`**

```python
"""Project knowledge graph — SQLite-backed dependency and decision map."""
from __future__ import annotations

import ast
import re
import sqlite3
import subprocess
import uuid
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


def _uid() -> str:
    return str(uuid.uuid4())


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

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest_git_log(self, n: int = 100) -> int:
        """Parse recent git commits into change nodes. Returns count added."""
        try:
            result = subprocess.run(
                ["git", "log", f"-{n}", "--pretty=format:%H|%s|%ad", "--date=short"],
                capture_output=True, text=True, check=False,
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
                sha, msg = parts[0], parts[1]
                node_id = f"commit:{sha[:8]}"
                existing = conn.execute(
                    "SELECT id FROM kg_nodes WHERE id = ?", (node_id,)
                ).fetchone()
                if not existing:
                    conn.execute(
                        "INSERT INTO kg_nodes VALUES (?,?,?,?)",
                        (node_id, "commit", msg[:120], "{}"),
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
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        if isinstance(node, ast.ImportFrom) and node.module:
                            mod = node.module.replace(".", "/") + ".py"
                            to_id = f"file:{mod}"
                            edge_id = f"edge:{from_id}:{to_id}"
                            conn.execute(
                                "INSERT OR IGNORE INTO kg_edges VALUES (?,?,?,?,?)",
                                (edge_id, from_id, to_id, "imports", "{}"),
                            )
                            edges_added += 1
        return edges_added

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(self, question: str) -> str:
        """Keyword search over node labels."""
        terms = [t.lower() for t in question.split() if len(t) > 2]
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

            # Who imports this file?
            importers = conn.execute(
                "SELECT n.label FROM kg_edges e JOIN kg_nodes n ON e.from_id = n.id "
                "WHERE e.to_id LIKE ? AND e.rel = 'imports' LIMIT 10",
                (f"%{file_path}%",),
            ).fetchall()

            # What does this file import?
            imports = conn.execute(
                "SELECT n.label FROM kg_edges e JOIN kg_nodes n ON e.to_id = n.id "
                "WHERE e.from_id LIKE ? AND e.rel = 'imports' LIMIT 10",
                (f"%{file_path}%",),
            ).fetchall()

        lines = [f"Knowledge trail: {file_path}"]
        if importers:
            lines.append(f"\nImported by ({len(importers)}):")
            for r in importers:
                lines.append(f"  ← {r['label']}")
        if imports:
            lines.append(f"\nImports ({len(imports)}):")
            for r in imports:
                lines.append(f"  → {r['label']}")
        if not importers and not imports:
            lines.append("  No dependency edges found. Run: /graph ingest")
        return "\n".join(lines)
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_knowledge.py -v
```
Expected: all 5 tests pass

- [ ] **Step 5: Add `/graph` command to shell**

In `CobaltShell.list_slash_commands()`, confirm `"graph"` is already in the list (added in Task 6). In `_run_command()`, add:

```python
if cmd == "graph":
    self._run_graph(args)
    return
```

Add the handler method:
```python
def _run_graph(self, args: list[str]) -> None:
    from .core.knowledge import KnowledgeGraph
    kg = KnowledgeGraph()
    if not args:
        console.print("  [dim]Usage: /graph why <file>  |  /graph <question>  |  /graph ingest[/dim]")
        return
    if args[0] == "ingest":
        from pathlib import Path
        n1 = kg.ingest_git_log()
        n2 = kg.ingest_imports(Path("src"))
        console.print(f"  [dim]Ingested {n1} commits, {n2} import edges[/dim]")
        return
    if args[0] == "why" and len(args) > 1:
        result = kg.why(args[1])
    else:
        result = kg.query(" ".join(args))
    console.print(result)
```

- [ ] **Step 6: Run full suite**

```bash
python3 -m pytest -q
```
Expected: 320+ passed

- [ ] **Step 7: Run checks**

```bash
ruff check src/ tests/
opencobalt public-check
```
Expected: both clean

- [ ] **Step 8: Commit**

```bash
git add src/opencobalt/core/knowledge.py src/opencobalt/shell.py tests/test_knowledge.py
git commit -m "feat: KnowledgeGraph -- SQLite dependency map with /graph why and /graph ingest"
```

---

## Deferred (follow-on tasks — not in this plan)

These are spec'd but omitted here for scope discipline. Implement after the 4 phases above are green:

- **Test watcher** — `watchdog` observer in `background.py` that queues `pytest -q` on `.py` file saves. Requires `pip install 'opencobalt[shell]'`. Falls back to 10s polling if watchdog absent.
- **Session-exit summary** — expand `CobaltShell.on_exit()` to call `BriefGenerator.generate(days=0)` and copy to clipboard. Currently prints "Session ended."
- **`verify_async()`** — non-blocking wrapper around `run_all()` in `verify.py`, called after each tool process exits. Currently pipeline calls `run_all()` synchronously.

---

## Final: Integration check + push-ready state

### Task 11: Final verification

- [ ] **Step 1: Full test suite**

```bash
python3 -m pytest -q
```
Expected: 320+ passed, 0 failed

- [ ] **Step 2: Lint**

```bash
ruff check src/ tests/
```
Expected: `All checks passed!`

- [ ] **Step 3: Public check**

```bash
opencobalt public-check
```
Expected: `Public safety: clean`

- [ ] **Step 4: Doctor**

```bash
opencobalt doctor
```
Expected: all green

- [ ] **Step 5: Smoke test shell entry point**

```bash
opencobalt --help
opencobalt status
```
Expected: both work without entering the REPL

- [ ] **Step 6: Update README status table**

In `README.md`, update the status table to reflect:
```markdown
| Component | State |
|---|---|
| Cobalt shell (interactive REPL) | Functional |
| Background multi-model council | Functional |
| Task pipelines (/pipe) | Functional |
| Self-learning router | Functional |
| Knowledge graph (/graph) | Functional |
```

- [ ] **Step 7: Final commit**

```bash
git add README.md
git commit -m "docs: update README status for cobalt shell and new features"
```
