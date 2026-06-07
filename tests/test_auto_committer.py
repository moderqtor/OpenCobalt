import subprocess
from pathlib import Path
import pytest
from opencobalt.core.auto_committer import AutoCommitter, CommitResult


def test_commit_returns_commit_result(tmp_path):
    (tmp_path / "src.py").write_text("code")
    messages: list[str] = []

    def run_git(args, cwd):
        if args[:2] == ["git", "commit"]:
            messages.append(args[3])
        if args == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="abc12345\n", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    committer = AutoCommitter(repo_path=tmp_path, run_git=run_git)
    result = committer.commit(
        session_id="session-uuid-1234-abcd",
        seed_task="implement auth",
        artifact_paths=["src.py"],
        artifact_lines=["impl_code by claude wave 0"],
        waves=1,
        retries=0,
        agents=["claude"],
        tests_info="5 passed / 5 total",
        verifier_info="0.87/1.0 (gemini)",
    )
    assert isinstance(result, CommitResult)
    assert result.sha == "abc12345"
    assert result.files_staged == ["src.py"]


def test_commit_message_contains_required_fields(tmp_path):
    (tmp_path / "src.py").write_text("code")
    messages: list[str] = []

    def run_git(args, cwd):
        if args[:2] == ["git", "commit"]:
            messages.append(args[3])
        if args == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="abc12345", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    committer = AutoCommitter(repo_path=tmp_path, run_git=run_git)
    committer.commit(
        session_id="session-uuid-1234-abcd",
        seed_task="implement auth with JWT",
        artifact_paths=["src.py"],
        artifact_lines=["impl_code by claude wave 0"],
        waves=2,
        retries=1,
        agents=["claude", "codex"],
        tests_info="47 passed / 47 total",
        verifier_info="0.9/1.0 (gemini)",
    )
    assert messages
    msg = messages[0]
    assert "feat(converge):" in msg
    assert "implement auth with JWT" in msg
    assert "session-uui" in msg  # first 8 chars of session_id
    assert "claude, codex" in msg
    assert "Co-Authored-By: Claude Sonnet 4.6" in msg


def test_commit_filters_env_files(tmp_path):
    (tmp_path / "src.py").write_text("code")
    staged: list[str] = []

    def run_git(args, cwd):
        if args[:2] == ["git", "add"]:
            staged.append(args[2])
        if args == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="abc12345", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    committer = AutoCommitter(repo_path=tmp_path, run_git=run_git)
    committer.commit(
        session_id="s", seed_task="task",
        artifact_paths=["src.py", ".env", "data.db", "__pycache__/x.pyc"],
        artifact_lines=[], waves=1, retries=0, agents=[],
        tests_info="n/a", verifier_info="n/a",
    )
    assert ".env" not in staged
    assert "data.db" not in staged
    assert "__pycache__/x.pyc" not in staged
    assert "src.py" in staged


def test_commit_returns_empty_when_no_stageable_files(tmp_path):
    calls: list = []

    def run_git(args, cwd):
        calls.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    committer = AutoCommitter(repo_path=tmp_path, run_git=run_git)
    result = committer.commit(
        session_id="s", seed_task="task", artifact_paths=[],
        artifact_lines=[], waves=1, retries=0, agents=[],
        tests_info="n/a", verifier_info="n/a",
    )
    assert result.sha == ""
    assert result.files_staged == []
    add_calls = [c for c in calls if c[:2] == ["git", "add"]]
    assert len(add_calls) == 0


def test_commit_fallback_when_artifact_paths_empty(tmp_path):
    (tmp_path / "changed.py").write_text("changed code")

    def run_git(args, cwd):
        if args == ["git", "diff", "--name-only", "HEAD"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="changed.py\n", stderr="")
        if args == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="abc12345", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    committer = AutoCommitter(repo_path=tmp_path, run_git=run_git)
    result = committer.commit(
        session_id="s", seed_task="task", artifact_paths=[],
        artifact_lines=[], waves=1, retries=0, agents=[],
        tests_info="n/a", verifier_info="n/a",
    )
    assert "changed.py" in result.files_staged


def test_commit_sha_truncated_to_8(tmp_path):
    (tmp_path / "f.py").write_text("x")

    def run_git(args, cwd):
        if args == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="abcdef1234567890\n", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    committer = AutoCommitter(repo_path=tmp_path, run_git=run_git)
    result = committer.commit(
        session_id="s", seed_task="t", artifact_paths=["f.py"],
        artifact_lines=[], waves=1, retries=0, agents=[],
        tests_info="n/a", verifier_info="n/a",
    )
    assert result.sha == "abcdef12"
