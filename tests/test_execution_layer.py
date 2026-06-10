"""Tests for Receipt-Backed Execution v0: policy, runner, adapters, engine.

No live agy/claude/codex/network calls. Subprocess use is limited to
/bin/echo (noop adapter) and mocked runs.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from opencobalt.execution import (
    AntigravityAdapter,
    CommandOptions,
    ExecutionEngine,
    ExecutionStore,
    NoopAdapter,
    OllamaAdapter,
    ProcessRunner,
    attach_artifact,
    available_runtimes,
    check_execution,
    classify_risk,
    get_adapter,
    hash_file,
    max_risk,
    verify_artifact,
)


def _engine(tmp_path: Path) -> ExecutionEngine:
    return ExecutionEngine(
        store=ExecutionStore(tmp_path / "ledger.db"),
        runner=ProcessRunner(artifact_dir=tmp_path / "artifacts"),
        events_path=tmp_path / "events.jsonl",
    )


def _agy_caps(**overrides) -> dict:
    caps = {
        "non_interactive_print": {"supported": True, "source": "runtime_discovered"},
        "non_interactive_mode": {"supported": True, "source": "runtime_discovered"},
        "model_selection": {"supported": True, "source": "runtime_discovered"},
        "sandbox_mode": {"supported": True, "source": "runtime_discovered"},
        "unsafe_skip_permissions": {"supported": True, "source": "runtime_discovered"},
    }
    caps.update(overrides)
    return caps


# ── Policy ────────────────────────────────────────────────────────────────────


class TestRiskClassification:
    def test_summarization_is_green(self):
        assert classify_risk("summarize docs/ANTIGRAVITY.md") == "green"

    def test_file_edit_is_yellow(self):
        assert classify_risk("edit the README file") == "yellow"

    @pytest.mark.parametrize(
        "task",
        [
            "read the .env values",
            "rotate the API key",
            "copy my ssh key",
            "print the deploy token",
            "automate browser login",
            "publish package to pypi",
            "update production config",
            "export browser profile cookies",
            "handle user credentials",
        ],
    )
    def test_credential_environment_tasks_are_red(self, task):
        assert classify_risk(task) == "red"

    @pytest.mark.parametrize(
        "task",
        ["rm -rf the build dir", "wipe the disk", "credential export to file", "delete everything"],
    )
    def test_destructive_tasks_are_black(self, task):
        assert classify_risk(task) == "black"

    def test_max_risk_picks_most_severe(self):
        assert max_risk("green", "red", "yellow") == "red"
        assert max_risk("green") == "green"
        assert max_risk("yellow", "black") == "black"


class TestPolicyGate:
    def test_dry_run_always_allowed(self):
        for level in ("green", "yellow", "red", "black"):
            decision = check_execution(level, dry_run=True, execute=False, approved=False)
            assert decision.allowed

    def test_green_executes_with_explicit_execute(self):
        assert check_execution("green", dry_run=False, execute=True, approved=False).allowed

    def test_yellow_requires_explicit_execute(self):
        assert not check_execution("yellow", dry_run=False, execute=False, approved=False).allowed
        assert check_execution("yellow", dry_run=False, execute=True, approved=False).allowed

    def test_red_requires_explicit_approval(self):
        denied = check_execution("red", dry_run=False, execute=True, approved=False)
        assert not denied.allowed
        assert denied.requires_approval
        assert check_execution("red", dry_run=False, execute=True, approved=True).allowed

    def test_black_blocked_even_with_approval(self):
        decision = check_execution("black", dry_run=False, execute=True, approved=True)
        assert not decision.allowed


# ── Process runner ────────────────────────────────────────────────────────────


class TestProcessRunner:
    def test_captures_stdout_and_succeeds(self, tmp_path):
        runner = ProcessRunner(artifact_dir=tmp_path)
        result = runner.run(["echo", "hello"], plan_id="p1", runtime="noop")
        assert result.status == "succeeded"
        assert result.return_code == 0
        assert "hello" in result.stdout_preview
        assert result.duration_ms is not None

    def test_writes_output_artifact_files(self, tmp_path):
        runner = ProcessRunner(artifact_dir=tmp_path)
        result = runner.run(["echo", "artifact content"], plan_id="p1", runtime="noop")
        assert result.stdout_path is not None
        assert "artifact content" in Path(result.stdout_path).read_text()

    def test_missing_executable_fails_cleanly(self, tmp_path):
        runner = ProcessRunner(artifact_dir=tmp_path)
        result = runner.run(
            ["definitely-not-a-real-binary-xyz"], plan_id="p1", runtime="noop"
        )
        assert result.status == "failed"
        assert "not found" in (result.error or "")

    def test_timeout_handled_cleanly(self, tmp_path):
        runner = ProcessRunner(artifact_dir=tmp_path)
        result = runner.run(
            ["sleep", "5"], plan_id="p1", runtime="noop", timeout_seconds=1
        )
        assert result.status == "timeout"
        assert "timed out" in (result.error or "")

    def test_rejects_non_list_argv(self, tmp_path):
        runner = ProcessRunner(artifact_dir=tmp_path)
        with pytest.raises(ValueError):
            runner.run("echo hello", plan_id="p1")  # type: ignore[arg-type]

    def test_never_uses_shell(self, tmp_path, monkeypatch):
        recorded: dict = {}

        def fake_run(argv, **kwargs):
            recorded["argv"] = argv
            recorded["kwargs"] = kwargs
            return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", fake_run)
        ProcessRunner(artifact_dir=tmp_path).run(["echo", "x"], plan_id="p1")
        assert isinstance(recorded["argv"], list)
        assert "shell" not in recorded["kwargs"]
        assert "env" not in recorded["kwargs"]  # no env dumping or overriding

    def test_captures_output_to_files_without_in_memory_capture(self, tmp_path, monkeypatch):
        recorded: dict = {}

        def fake_run(argv, **kwargs):
            recorded["kwargs"] = kwargs
            kwargs["stdout"].write("OPENAI_API_KEY=sk-testsecret123456789\nnormal output\n")
            kwargs["stderr"].write("stderr output\n")
            return subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", fake_run)
        result = ProcessRunner(artifact_dir=tmp_path).run(["echo", "x"], plan_id="p1")
        assert "capture_output" not in recorded["kwargs"]
        assert recorded["kwargs"]["stdout"] is not subprocess.PIPE
        assert recorded["kwargs"]["stderr"] is not subprocess.PIPE
        assert result.stdout_path is not None
        assert "sk-testsecret123456789" not in result.stdout_preview
        assert "OPENAI_API_KEY=<redacted>" in result.stdout_preview
        assert "normal output" in Path(result.stdout_path).read_text(encoding="utf-8")

    def test_runner_source_has_no_shell_true(self):
        source = Path("src/opencobalt/execution/runner.py").read_text()
        assert "shell=True" not in source


# ── Adapters ──────────────────────────────────────────────────────────────────


class TestAdapters:
    def test_registry_knows_v0_runtimes(self):
        assert {"google-antigravity", "ollama", "noop"} <= set(available_runtimes())

    def test_unknown_runtime_fails_cleanly(self):
        with pytest.raises(KeyError, match="unknown runtime"):
            get_adapter("skynet")

    def test_noop_adapter_builds_echo(self):
        assert NoopAdapter().build_command("hello") == ["echo", "hello"]

    def test_ollama_adapter_builds_run_argv(self):
        argv = OllamaAdapter().build_command("hello", CommandOptions(model="qwen3"))
        assert argv == ["ollama", "run", "qwen3", "hello"]

    def test_antigravity_print_command(self):
        adapter = AntigravityAdapter(capabilities=_agy_caps())
        assert adapter.build_command("hello") == ["agy", "--print", "hello"]

    def test_antigravity_model_command(self):
        adapter = AntigravityAdapter(capabilities=_agy_caps())
        argv = adapter.build_command("hello", CommandOptions(model="gemini-3-pro"))
        assert argv == ["agy", "--model", "gemini-3-pro", "--print", "hello"]

    def test_antigravity_sandbox_command(self):
        adapter = AntigravityAdapter(capabilities=_agy_caps())
        argv = adapter.build_command("hello", CommandOptions(sandbox=True))
        assert argv == ["agy", "--sandbox", "--print", "hello"]

    def test_antigravity_never_skips_permissions_by_default(self):
        adapter = AntigravityAdapter(capabilities=_agy_caps())
        argv = adapter.build_command("hello", CommandOptions(dangerously_skip_permissions=True))
        assert "--dangerously-skip-permissions" not in argv

    def test_antigravity_unsafe_override_warns(self):
        adapter = AntigravityAdapter(capabilities=_agy_caps())
        with pytest.warns(RuntimeWarning):
            argv = adapter.build_command(
                "hello",
                CommandOptions(
                    dangerously_skip_permissions=True,
                    allow_dangerously_skip_permissions=True,
                ),
            )
        assert "--dangerously-skip-permissions" in argv

    def test_antigravity_without_print_support_fails_cleanly(self):
        caps = _agy_caps(
            non_interactive_print={"supported": None, "source": "unknown"},
            non_interactive_mode={"supported": None, "source": "unknown"},
        )
        adapter = AntigravityAdapter(capabilities=caps)
        assert not adapter.supports_non_interactive()
        with pytest.raises(ValueError):
            adapter.build_command("hello")


# ── Artifacts ─────────────────────────────────────────────────────────────────


class TestArtifacts:
    def test_attach_computes_sha256(self, tmp_path):
        f = tmp_path / "report.txt"
        f.write_text("hello receipts\n")
        artifact = attach_artifact(f, source_runtime="noop", artifact_type="report")
        expected = hashlib.sha256(b"hello receipts\n").hexdigest()
        assert artifact.sha256 == expected
        assert artifact.size_bytes == len(b"hello receipts\n")

    def test_hash_file_streams_large_file(self, tmp_path):
        f = tmp_path / "big.bin"
        payload = b"x" * (3 * 1024 * 1024)
        f.write_bytes(payload)
        assert hash_file(f) == hashlib.sha256(payload).hexdigest()

    def test_unknown_type_normalizes(self, tmp_path):
        f = tmp_path / "thing.txt"
        f.write_text("x")
        artifact = attach_artifact(f, source_runtime="noop", artifact_type="not-a-type")
        assert artifact.artifact_type == "unknown"

    def test_verify_passes_when_unchanged(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("stable")
        artifact = attach_artifact(f, source_runtime="noop")
        assert verify_artifact(artifact).verified

    def test_verify_fails_after_mutation(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("original")
        artifact = attach_artifact(f, source_runtime="noop")
        f.write_text("tampered")
        verification = verify_artifact(artifact)
        assert not verification.verified
        assert "mismatch" in verification.reason

    def test_verify_missing_file_fails_cleanly(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        artifact = attach_artifact(f, source_runtime="noop")
        f.unlink()
        verification = verify_artifact(artifact)
        assert not verification.verified
        assert verification.reason == "file missing"

    def test_attach_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            attach_artifact(tmp_path / "nope.txt", source_runtime="noop")


# ── Engine: plans, receipts, verification ─────────────────────────────────────


class TestExecutionEngine:
    def test_dry_run_creates_plan_and_receipt_without_subprocess(self, tmp_path, monkeypatch):
        def explode(*args, **kwargs):
            raise AssertionError("dry-run must not start a subprocess")

        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", explode)
        engine = _engine(tmp_path)
        outcome = engine.run_task("hello", runtime="noop")
        assert outcome.plan.dry_run
        assert outcome.result is None
        assert outcome.receipt.verification_status == "unverified"
        assert engine.store.get_plan(outcome.plan.plan_id) is not None
        assert engine.store.get_receipt(outcome.receipt.receipt_id) is not None

    def test_plan_records_runtime_task_risk_approval(self, tmp_path):
        outcome = _engine(tmp_path).run_task("rotate the api key", runtime="noop")
        assert outcome.plan.runtime == "noop"
        assert outcome.plan.risk_level == "red"
        assert outcome.plan.approval_required
        assert outcome.plan.steps[0].command_argv[0] == "echo"

    def test_runtime_auto_selection_uses_router(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        outcome = _engine(tmp_path).run_task("summarize this paragraph into a tag")
        assert outcome.plan.runtime == "ollama"
        assert outcome.route_reason is not None
        assert "Routed to" in outcome.route_reason

    def test_execute_creates_receipt_with_artifacts(self, tmp_path):
        engine = _engine(tmp_path)
        outcome = engine.run_task("hello", runtime="noop", execute=True)
        assert outcome.executed
        assert outcome.result is not None and outcome.result.status == "succeeded"
        receipt = outcome.receipt
        assert receipt.execution_id == outcome.result.execution_id
        assert receipt.artifact_ids, "executed receipt must reference output artifacts"
        assert receipt.command_plan == ["echo", "hello"]
        assert receipt.verification_status == "verified"

    def test_receipt_stores_capabilities_snapshot(self, tmp_path):
        outcome = _engine(tmp_path).run_task("hello", runtime="noop", execute=True)
        assert outcome.receipt.capabilities_snapshot.get("echo_only", {}).get("supported")

    def test_red_task_blocked_without_approval(self, tmp_path, monkeypatch):
        def explode(*args, **kwargs):
            raise AssertionError("blocked task must not start a subprocess")

        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", explode)
        outcome = _engine(tmp_path).run_task("rotate the api key", runtime="noop", execute=True)
        assert not outcome.policy.allowed
        assert outcome.result is None
        assert engine_receipt_exists(tmp_path, outcome.receipt.receipt_id)

    def test_red_task_executes_with_approval(self, tmp_path):
        outcome = _engine(tmp_path).run_task(
            "rotate the api key", runtime="noop", execute=True, approved=True
        )
        assert outcome.policy.allowed
        assert outcome.executed

    def test_black_task_blocked_even_with_approval(self, tmp_path):
        outcome = _engine(tmp_path).run_task(
            "rm -rf the build dir", runtime="noop", execute=True, approved=True
        )
        assert not outcome.policy.allowed
        assert outcome.result is None

    def test_verify_receipt_fails_after_artifact_mutation(self, tmp_path):
        engine = _engine(tmp_path)
        outcome = engine.run_task("hello", runtime="noop", execute=True)
        artifact = engine.store.get_artifact(outcome.receipt.artifact_ids[0])
        assert artifact is not None
        Path(artifact.path).write_text("tampered after the fact")
        status = engine.verify_receipt(outcome.receipt.receipt_id)
        assert status == "failed"
        refreshed = engine.store.get_receipt(outcome.receipt.receipt_id)
        assert refreshed is not None and refreshed.verification_status == "failed"

    def test_verify_unknown_receipt_raises(self, tmp_path):
        with pytest.raises(KeyError):
            _engine(tmp_path).verify_receipt("no-such-receipt")

    def test_antigravity_execute_with_mocked_runner(self, tmp_path, monkeypatch):
        def fake_run(argv, **kwargs):
            assert argv == ["agy", "--print", "hello"]
            kwargs["stdout"].write("agent reply")
            return subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", fake_run)
        engine = _engine(tmp_path)
        adapter = AntigravityAdapter(capabilities=_agy_caps())
        outcome = engine.run_task(
            "hello", runtime="google-antigravity", execute=True, adapter=adapter
        )
        assert outcome.executed
        assert outcome.result is not None
        assert "agent reply" in outcome.result.stdout_preview
        assert outcome.receipt.verification_status == "verified"
        assert "--dangerously-skip-permissions" not in outcome.receipt.command_plan

    def test_events_are_emitted_and_persisted(self, tmp_path):
        engine = _engine(tmp_path)
        outcome = engine.run_task("hello", runtime="noop", execute=True)
        types = [e["event_type"] for e in outcome.events]
        assert "task.received" in types
        assert "route.selected" in types
        assert "plan.created" in types
        assert "policy.checked" in types
        assert "execution.started" in types
        assert "execution.succeeded" in types
        assert "artifact.created" in types
        assert "receipt.created" in types
        assert "verification.passed" in types
        assert (tmp_path / "events.jsonl").exists()

    def test_event_sink_receives_events(self, tmp_path):
        seen: list[str] = []
        engine = ExecutionEngine(
            store=ExecutionStore(tmp_path / "ledger.db"),
            runner=ProcessRunner(artifact_dir=tmp_path / "artifacts"),
            events_path=tmp_path / "events.jsonl",
            event_sink=lambda e: seen.append(e["event_type"]),
        )
        engine.run_task("hello", runtime="noop")
        assert "task.received" in seen


def engine_receipt_exists(tmp_path: Path, receipt_id: str) -> bool:
    return ExecutionStore(tmp_path / "ledger.db").get_receipt(receipt_id) is not None


# ── Store round-trips ─────────────────────────────────────────────────────────


class TestExecutionStore:
    def test_plan_round_trip(self, tmp_path):
        from opencobalt.execution import ExecutionPlan, ExecutionStep

        store = ExecutionStore(tmp_path / "ledger.db")
        plan = ExecutionPlan(
            task="t",
            runtime="noop",
            risk_level="yellow",
            approval_required=False,
            steps=[ExecutionStep(runtime="noop", command_argv=["echo", "t"])],
            dry_run=True,
        )
        store.save_plan(plan)
        loaded = store.get_plan(plan.plan_id)
        assert loaded is not None
        assert loaded.task == "t"
        assert loaded.steps[0].command_argv == ["echo", "t"]
        assert loaded.dry_run

    def test_receipt_filters(self, tmp_path):
        from opencobalt.execution import WorkReceipt

        store = ExecutionStore(tmp_path / "ledger.db")
        store.save_receipt(WorkReceipt(plan_id="p1", task="a", selected_runtime="noop"))
        store.save_receipt(
            WorkReceipt(
                plan_id="p2",
                task="b",
                selected_runtime="ollama",
                verification_status="verified",
            )
        )
        assert len(store.list_receipts()) == 2
        assert len(store.list_receipts(runtime="ollama")) == 1
        assert len(store.list_receipts(verification_status="verified")) == 1

    def test_schema_coexists_with_main_ledger(self, tmp_path):
        from opencobalt.core.ledger import Ledger

        db = tmp_path / "ledger.db"
        Ledger(db)  # create main schema first
        store = ExecutionStore(db)  # must not break existing tables
        assert store.list_receipts() == []
        assert Ledger(db).count_events() == 0
