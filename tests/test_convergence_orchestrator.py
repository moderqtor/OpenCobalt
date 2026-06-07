import subprocess
from pathlib import Path
import pytest
from opencobalt.core.artifact_bus import ArtifactBus, ArtifactType
from opencobalt.core.auto_committer import AutoCommitter, CommitResult
from opencobalt.core.convergence_checker import (
    ConvergenceChecker,
    TestsGate,
    VerifierGate,
)
from opencobalt.core.convergence_orchestrator import ConvergenceOrchestrator, ConvergenceSession


def _make_checker(pass_result: bool = True) -> ConvergenceChecker:
    verifier_response = (
        '{"score": 0.9, "approved": true, "feedback": "ok"}'
        if pass_result
        else '{"score": 0.3, "approved": false, "feedback": "bad output"}'
    )
    return ConvergenceChecker(
        tests_gate=TestsGate(run_tests=lambda: (True, "5 passed")),
        verifier_gate=VerifierGate(consult=lambda _: verifier_response),
    )


def _make_committer(tmp_path: Path) -> AutoCommitter:
    def run_git(args, cwd):
        if args == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="abc12345\n", stderr="")
        if args[:2] == ["git", "diff"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="diff --git a/f.py\n", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
    return AutoCommitter(repo_path=tmp_path, run_git=run_git)


def test_run_returns_convergence_session(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    orch = ConvergenceOrchestrator(
        artifact_bus=bus,
        checker=_make_checker(True),
        committer=_make_committer(tmp_path),
        execute_subtask=lambda prompt, tool: "output text",
    )
    session = orch.run("implement auth")
    assert isinstance(session, ConvergenceSession)
    assert session.id != ""
    assert session.seed_task == "implement auth"
    assert session.finished_at is not None


def test_run_publishes_impl_artifacts(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    orch = ConvergenceOrchestrator(
        artifact_bus=bus,
        checker=_make_checker(True),
        committer=_make_committer(tmp_path),
        execute_subtask=lambda prompt, tool: "output",
    )
    session = orch.run("implement auth")
    impl_artifacts = bus.subscribe([ArtifactType.IMPL_CODE], session.id)
    assert len(impl_artifacts) >= 1
    assert impl_artifacts[0].content == "output"


def test_run_converged_on_passing_gates(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    orch = ConvergenceOrchestrator(
        artifact_bus=bus,
        checker=_make_checker(True),
        committer=_make_committer(tmp_path),
        execute_subtask=lambda prompt, tool: "output",
    )
    session = orch.run("implement auth")
    assert session.status == "converged"


def test_run_failed_on_persistent_gate_failure(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    orch = ConvergenceOrchestrator(
        artifact_bus=bus,
        checker=_make_checker(False),
        committer=_make_committer(tmp_path),
        execute_subtask=lambda prompt, tool: "output",
    )
    session = orch.run("implement auth")
    assert session.status == "failed"


def test_error_context_published_on_gate_failure(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    orch = ConvergenceOrchestrator(
        artifact_bus=bus,
        checker=_make_checker(False),
        committer=_make_committer(tmp_path),
        execute_subtask=lambda prompt, tool: "output",
    )
    session = orch.run("implement auth")
    error_artifacts = bus.subscribe([ArtifactType.ERROR_CONTEXT], session.id)
    assert len(error_artifacts) > 0


def test_execute_subtask_receives_context_on_retry(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    prompts_seen: list[str] = []

    call_count = 0

    def checker_fn():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return False
        return True

    class ToggleChecker(ConvergenceChecker):
        def check(self, task_types, task="", diff="", retry_count=0):
            from opencobalt.core.convergence_checker import ConvergenceResult
            ok = checker_fn()
            return ConvergenceResult(
                passed=ok,
                tests_ok=ok,
                verifier_ok=None,
                verifier_score=None,
                retry_count=retry_count,
                feedback="" if ok else "tests failed",
            )

    def capture_execute(prompt: str, tool: str) -> str:
        prompts_seen.append(prompt)
        return "output"

    orch = ConvergenceOrchestrator(
        artifact_bus=bus,
        checker=ToggleChecker(),
        committer=_make_committer(tmp_path),
        execute_subtask=capture_execute,
    )
    session = orch.run("implement auth")
    assert len(prompts_seen) >= 2
    if len(prompts_seen) >= 2:
        assert len(prompts_seen[-1]) >= len(prompts_seen[0])


def test_commit_called_on_convergence(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    commit_called = [False]

    class SpyCommitter(AutoCommitter):
        def commit(self, **kwargs):
            commit_called[0] = True
            return CommitResult(sha="abc12345", message="msg", files_staged=[])

    orch = ConvergenceOrchestrator(
        artifact_bus=bus,
        checker=_make_checker(True),
        committer=SpyCommitter(repo_path=tmp_path),
        execute_subtask=lambda prompt, tool: "output",
    )
    orch.run("implement auth")
    assert commit_called[0] is True


def test_commit_not_called_on_failure(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    commit_called = [False]

    class SpyCommitter(AutoCommitter):
        def commit(self, **kwargs):
            commit_called[0] = True
            return CommitResult(sha="abc12345", message="msg", files_staged=[])

    orch = ConvergenceOrchestrator(
        artifact_bus=bus,
        checker=_make_checker(False),
        committer=SpyCommitter(repo_path=tmp_path),
        execute_subtask=lambda prompt, tool: "output",
    )
    orch.run("implement auth")
    assert commit_called[0] is False


def test_session_waves_counted(tmp_path):
    bus = ArtifactBus(tmp_path / "artifacts.db")
    orch = ConvergenceOrchestrator(
        artifact_bus=bus,
        checker=_make_checker(True),
        committer=_make_committer(tmp_path),
        execute_subtask=lambda prompt, tool: "output",
    )
    session = orch.run("implement auth with tests")
    assert session.total_waves >= 1
