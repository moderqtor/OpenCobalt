"""Verification runner.

Runs safe local verification commands and records results to the ledger.
Never runs destructive commands. Always captures output.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from .models import VerificationResult
from .public_safety import ScanResult, scan_directory


def run_pytest(root: Path | None = None) -> VerificationResult:
    """Run pytest and return a VerificationResult."""
    root = root or Path(".")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--tb=short", "-q"],
        capture_output=True,
        text=True,
        cwd=root,
    )
    output = (result.stdout + result.stderr).strip()
    summary = output.splitlines()[-1] if output.splitlines() else "no output"
    return VerificationResult(
        command="pytest",
        exit_code=result.returncode,
        passed=result.returncode == 0,
        output_summary=summary[:500],
    )


def run_public_check(root: Path | None = None) -> VerificationResult:
    """Run the public safety scanner and return a VerificationResult."""
    root = (root or Path(".")).resolve()
    scan: ScanResult = scan_directory(root)
    summary = scan.summary()
    return VerificationResult(
        command="public-check",
        exit_code=0 if scan.is_clean else 1,
        passed=scan.is_clean,
        output_summary=summary[:500],
    )


def run_all(root: Path | None = None, ledger=None) -> list[VerificationResult]:
    """Run pytest and public-check. Optionally persist results to ledger."""
    results = [run_pytest(root), run_public_check(root)]
    if ledger is not None:
        for r in results:
            ledger.insert_verification_result(r)
    return results


def verify_async(runner: Any, root: Path, ledger: Any) -> None:
    """Queue a verify run in the background. Results appear via runner.drain()."""
    def _run() -> str:
        results = run_all(root=root, ledger=ledger)
        passed = all(r.passed for r in results)
        summary = " · ".join(r.output_summary for r in results)
        return f"{'VERIFIED' if passed else 'FAILED'}: {summary}"

    runner.submit("verify-async", _run)
