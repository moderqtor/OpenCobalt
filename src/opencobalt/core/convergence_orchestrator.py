"""Top-level convergence orchestrator: DAG execution, gating, auto-commit."""

from __future__ import annotations

import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.panel import Panel

from .artifact_bus import AgentArtifact, ArtifactBus, ArtifactType
from .auto_committer import AutoCommitter, CommitResult
from .convergence_checker import ConvergenceChecker, ConvergenceResult
from .dag_decomposer import DAGDecomposer, DAGSubTask

_console = Console()
_COBALT = "#7B9EFF"
_GREEN = "#3DFFA0"
_RED = "#FF5577"
_MAX_RETRIES = 3


@dataclass
class ConvergenceSession:
    id: str
    seed_task: str
    status: str = "queued"
    started_at: float = 0.0
    finished_at: float | None = None
    total_waves: int = 0
    total_retries: int = 0
    commit_sha: str | None = None
    log_path: Path | None = None


def _default_execute_subtask(prompt: str, tool: str) -> str:
    import shutil
    from .council import consult_subprocess

    model_map = {
        "claude-code": "claude",
        "codex-cli": "codex",
        "gemini-cli": "gemini",
        "ollama": "ollama",
    }
    model = model_map.get(tool, "claude")
    if not shutil.which(model):
        return f"[{model}: not on PATH]"
    return consult_subprocess(prompt, model=model, intent="implement", timeout=120)


class ConvergenceOrchestrator:
    """Decomposes a task into a DAG, executes waves, checks convergence, auto-commits."""

    def __init__(
        self,
        decomposer: DAGDecomposer | None = None,
        artifact_bus: ArtifactBus | None = None,
        checker: ConvergenceChecker | None = None,
        committer: AutoCommitter | None = None,
        ledger=None,
        execute_subtask: Callable[[str, str], str] | None = None,
    ) -> None:
        self._decomposer = decomposer or DAGDecomposer()
        self._bus = artifact_bus or ArtifactBus()
        self._checker = checker or ConvergenceChecker()
        self._committer = committer or AutoCommitter()
        self._ledger = ledger
        self._execute_subtask = execute_subtask or _default_execute_subtask

    def run(self, seed_task: str, resume_session_id: str | None = None) -> ConvergenceSession:
        session_id = resume_session_id or str(uuid.uuid4())
        session = ConvergenceSession(
            id=session_id,
            seed_task=seed_task,
            status="running",
            started_at=time.time(),
        )
        self._persist_session(session)

        subtasks = self._decomposer.decompose_dag(seed_task)
        waves = self._decomposer.to_waves(subtasks)
        session.total_waves = len(waves)

        all_converged = True
        last_result: ConvergenceResult | None = None

        for wave_idx, wave in enumerate(waves):
            result = self._run_wave(session, wave, wave_idx)
            last_result = result
            if not result.passed:
                all_converged = False

        session.finished_at = time.time()
        session.status = "converged" if all_converged else "failed"
        self._persist_session(session)

        if all_converged:
            commit = self._do_commit(session, subtasks, last_result)
            session.commit_sha = commit.sha

        self._print_summary(session)
        return session

    def _run_wave(
        self,
        session: ConvergenceSession,
        wave: list[DAGSubTask],
        wave_idx: int,
    ) -> ConvergenceResult:
        result = ConvergenceResult(
            passed=False, tests_ok=None, verifier_ok=None,
            verifier_score=None, retry_count=0, feedback="no check performed",
        )
        retry_count = 0

        while retry_count <= _MAX_RETRIES:
            outputs: dict[str, str] = {}
            with ThreadPoolExecutor(max_workers=min(len(wave), 6)) as pool:
                futures = {
                    pool.submit(
                        self._execute_subtask,
                        self._build_prompt(session.id, st),
                        st.preferred_tool,
                    ): st
                    for st in wave
                }
                for future in as_completed(futures):
                    st = futures[future]
                    try:
                        outputs[st.id] = future.result(timeout=300)
                    except Exception as exc:
                        outputs[st.id] = f"[error: {exc}]"

            for st in wave:
                output = outputs.get(st.id, "")
                for artifact_type in st.produces:
                    self._bus.publish(AgentArtifact(
                        id=str(uuid.uuid4()),
                        session_id=session.id,
                        iteration=retry_count,
                        wave=wave_idx,
                        producer=st.preferred_tool,
                        type=artifact_type,
                        content=output,
                        metadata={"task_type": st.task_type},
                        timestamp=time.time(),
                    ))

            task_types = list({st.task_type for st in wave})
            diff = self._get_diff()
            result = self._checker.check(
                task_types=task_types,
                task=session.seed_task,
                diff=diff,
                retry_count=retry_count,
            )
            self._persist_wave_result(session.id, wave_idx, result)

            if result.passed:
                return result

            if retry_count >= _MAX_RETRIES:
                break

            if result.feedback:
                self._bus.publish(AgentArtifact(
                    id=str(uuid.uuid4()),
                    session_id=session.id,
                    iteration=retry_count,
                    wave=wave_idx,
                    producer="convergence-checker",
                    type=ArtifactType.ERROR_CONTEXT,
                    content=result.feedback,
                    metadata={},
                    timestamp=time.time(),
                ))

            retry_count += 1
            session.total_retries += 1

        return result

    def _build_prompt(self, session_id: str, st: DAGSubTask) -> str:
        ctx = self._bus.context_for(
            st.consumes + [ArtifactType.ERROR_CONTEXT], session_id
        )
        if ctx:
            return f"{ctx}\n\n{st.prompt}"
        return st.prompt

    def _get_diff(self) -> str:
        try:
            r = subprocess.run(
                ["git", "diff", "HEAD"],
                capture_output=True, text=True, timeout=30,
            )
            return r.stdout[:3000] if r.returncode == 0 else ""
        except Exception:
            return ""

    def _do_commit(
        self,
        session: ConvergenceSession,
        subtasks: list[DAGSubTask],
        last_result: ConvergenceResult | None,
    ) -> CommitResult:
        artifact_paths: list[str] = []
        artifact_lines: list[str] = []
        agents: list[str] = []

        for art_type in (ArtifactType.IMPL_CODE, ArtifactType.TEST_CODE,
                         ArtifactType.DOC_TEXT, ArtifactType.REVIEW_SCORE):
            for a in self._bus.subscribe([art_type], session.id):
                paths = a.metadata.get("file_paths", [])
                if isinstance(paths, list):
                    artifact_paths.extend(paths)
                artifact_lines.append(
                    f"{a.type:<15} by {a.producer:<12} wave {a.wave}"
                )
                if a.producer not in agents:
                    agents.append(a.producer)

        tests_info = "n/a"
        verifier_info = "n/a"
        if last_result:
            if last_result.tests_ok is not None:
                tests_info = "passed" if last_result.tests_ok else "failed"
            if last_result.verifier_score is not None:
                verifier_info = f"{last_result.verifier_score:.2f}/1.0"

        return self._committer.commit(
            session_id=session.id,
            seed_task=session.seed_task,
            artifact_paths=artifact_paths,
            artifact_lines=artifact_lines,
            waves=session.total_waves,
            retries=session.total_retries,
            agents=agents,
            tests_info=tests_info,
            verifier_info=verifier_info,
        )

    def _persist_session(self, session: ConvergenceSession) -> None:
        if self._ledger is None:
            return
        try:
            self._ledger.upsert_convergence_session(
                session_id=session.id,
                seed_task=session.seed_task,
                status=session.status,
                started_at=session.started_at,
                finished_at=session.finished_at,
                total_waves=session.total_waves,
                total_retries=session.total_retries,
                commit_sha=session.commit_sha,
                log_path=str(session.log_path) if session.log_path else None,
            )
        except Exception:
            pass

    def _persist_wave_result(
        self, session_id: str, wave_idx: int, result: ConvergenceResult
    ) -> None:
        if self._ledger is None:
            return
        try:
            self._ledger.insert_wave_result(
                session_id=session_id,
                wave=wave_idx,
                tests_ok=result.tests_ok,
                verifier_score=result.verifier_score,
                verifier_ok=result.verifier_ok,
                passed=result.passed,
                retry_count=result.retry_count,
                feedback=result.feedback,
            )
        except Exception:
            pass

    def _print_summary(self, session: ConvergenceSession) -> None:
        color = _GREEN if session.status == "converged" else _RED
        elapsed = (session.finished_at or time.time()) - session.started_at
        m, s = divmod(int(elapsed), 60)
        elapsed_str = f"{m}:{s:02d}" if m else f"{s}s"
        commit_line = f"\n  [dim]commit: {session.commit_sha}[/dim]" if session.commit_sha else ""
        _console.print(Panel(
            f"[{color}]{session.status}[/{color}]  "
            f"[dim]{session.total_waves} waves · {session.total_retries} retries · "
            f"{elapsed_str}[/dim]{commit_line}",
            title=f"[bold {_COBALT}]convergence complete[/bold {_COBALT}]",
            border_style=_COBALT,
        ))
