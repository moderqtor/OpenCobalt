import pytest

from opencobalt.core.convergence_checker import (
    ConvergenceChecker,
    TestsGate,
    VerifierGate,
)


def _passing_tests() -> tuple[bool, str]:
    return (True, "5 passed")


def _failing_tests() -> tuple[bool, str]:
    return (False, "1 failed: test_foo\nAssertionError: expected True")


def _approving_verifier(prompt: str) -> str:
    return '{"score": 0.88, "approved": true, "feedback": "looks good"}'


def _rejecting_verifier(prompt: str) -> str:
    return '{"score": 0.4, "approved": false, "feedback": "missing error handling"}'


def test_tests_gate_pass():
    gate = TestsGate(run_tests=_passing_tests)
    ok, output = gate.check()
    assert ok is True
    assert "5 passed" in output


def test_tests_gate_fail():
    gate = TestsGate(run_tests=_failing_tests)
    ok, output = gate.check()
    assert ok is False
    assert "failed" in output


def test_verifier_gate_approve():
    gate = VerifierGate(consult=_approving_verifier)
    ok, score, feedback = gate.check("implement auth", "diff here")
    assert ok is True
    assert score == pytest.approx(0.88)
    assert "good" in feedback


def test_verifier_gate_reject():
    gate = VerifierGate(consult=_rejecting_verifier)
    ok, score, feedback = gate.check("implement auth", "diff here")
    assert ok is False
    assert score == pytest.approx(0.4)
    assert "error handling" in feedback


def test_verifier_gate_bad_json_returns_zero_score():
    gate = VerifierGate(consult=lambda _: "not json at all")
    ok, score, feedback = gate.check("task", "diff")
    assert ok is False
    assert score == pytest.approx(0.0)


def test_verifier_gate_json_in_prose():
    gate = VerifierGate(consult=lambda _: 'Here is my review: {"score": 0.9, "approved": true, "feedback": "ok"}')
    ok, score, _ = gate.check("task", "diff")
    assert ok is True
    assert score == pytest.approx(0.9)


def test_checker_impl_uses_both_gates():
    checker = ConvergenceChecker(
        tests_gate=TestsGate(run_tests=_passing_tests),
        verifier_gate=VerifierGate(consult=_approving_verifier),
    )
    result = checker.check(["impl"], task="implement auth", diff="diff")
    assert result.tests_ok is True
    assert result.verifier_ok is True
    assert result.passed is True


def test_checker_refactor_uses_tests_gate_only():
    checker = ConvergenceChecker(
        tests_gate=TestsGate(run_tests=_passing_tests),
        verifier_gate=VerifierGate(consult=_rejecting_verifier),
    )
    result = checker.check(["refactor"], task="refactor code", diff="diff")
    assert result.tests_ok is True
    assert result.verifier_ok is None
    assert result.passed is True


def test_checker_docs_uses_verifier_gate_only():
    checker = ConvergenceChecker(
        tests_gate=TestsGate(run_tests=_failing_tests),
        verifier_gate=VerifierGate(consult=_approving_verifier),
    )
    result = checker.check(["docs"], task="write docs", diff="diff")
    assert result.tests_ok is None
    assert result.verifier_ok is True
    assert result.passed is True


def test_checker_mixed_types_union_of_gates():
    checker = ConvergenceChecker(
        tests_gate=TestsGate(run_tests=_passing_tests),
        verifier_gate=VerifierGate(consult=_approving_verifier),
    )
    result = checker.check(["impl", "docs"], task="task", diff="diff")
    assert result.tests_ok is True
    assert result.verifier_ok is True


def test_checker_failed_result_has_feedback():
    checker = ConvergenceChecker(
        tests_gate=TestsGate(run_tests=_failing_tests),
        verifier_gate=VerifierGate(consult=_rejecting_verifier),
    )
    result = checker.check(["impl"], task="task", diff="diff")
    assert result.passed is False
    assert result.feedback != ""
    assert result.feedback != "all gates passed"


def test_checker_passed_result_has_positive_feedback():
    checker = ConvergenceChecker(
        tests_gate=TestsGate(run_tests=_passing_tests),
        verifier_gate=VerifierGate(consult=_approving_verifier),
    )
    result = checker.check(["impl"], task="task", diff="diff")
    assert result.passed is True
    assert "passed" in result.feedback


def test_convergence_result_retry_count_stored():
    checker = ConvergenceChecker(
        tests_gate=TestsGate(run_tests=_passing_tests),
        verifier_gate=VerifierGate(consult=_approving_verifier),
    )
    result = checker.check(["impl"], task="t", diff="d", retry_count=2)
    assert result.retry_count == 2
