from pathlib import Path

from opencobalt.core.verify import run_public_check


def test_run_public_check_passes_with_generated_target_artifacts(tmp_path: Path):
    target = tmp_path / "ui" / "src-tauri" / "target" / "debug"
    target.mkdir(parents=True)
    (target / "opencobalt-desktop").write_bytes(b"x" * (11 * 1024 * 1024))
    (target / "__global-api-script.js").write_text("~/cobaltos-vault generated path")

    result = run_public_check(tmp_path)

    assert result.command == "public-check"
    assert result.exit_code == 0
    assert result.passed
    assert "No public-safety issues detected" in result.output_summary


def test_run_public_check_fails_with_env_file(tmp_path: Path):
    (tmp_path / ".env").write_text("OPENCOBALT_TOKEN=abcdefg\n")

    result = run_public_check(tmp_path)

    assert result.command == "public-check"
    assert result.exit_code == 1
    assert not result.passed
    assert ".env file present" in result.output_summary
