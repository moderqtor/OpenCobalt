
from opencobalt.core.public_safety import ScanResult, scan_directory


def test_clean_directory_is_clean(tmp_path):
    (tmp_path / "README.md").write_text("# Hello world\nThis is a clean file.")
    result = scan_directory(tmp_path)
    assert result.is_clean


def test_env_file_is_flagged(tmp_path):
    (tmp_path / ".env").write_text("SECRET=something")
    result = scan_directory(tmp_path)
    assert result.env_files_found
    assert not result.is_clean


def test_env_example_is_not_flagged(tmp_path):
    (tmp_path / ".env.example").write_text("SECRET=placeholder")
    result = scan_directory(tmp_path)
    assert not result.env_files_found


def test_node_modules_is_skipped(tmp_path):
    # node_modules is gitignored and never committed -- scanner skips it silently.
    nm = tmp_path / "node_modules"
    nm.mkdir()
    (nm / "react.js").write_text('const password = "ignored"')
    result = scan_directory(tmp_path)
    assert result.is_clean


def test_generated_build_directories_are_skipped(tmp_path):
    for dirname in ("target", "dist", "build"):
        generated = tmp_path / dirname
        generated.mkdir()
        (generated / "large-artifact.bin").write_bytes(b"x" * (11 * 1024 * 1024))
        (generated / "bundle.js").write_text("sourceMappingURL=/Users/colin/cobaltos-vault/index.js")

    result = scan_directory(tmp_path)

    assert result.is_clean
    assert result.oversized_files == []
    assert result.vault_path_hits == []


def test_nested_tauri_target_directory_is_skipped(tmp_path):
    tauri_target = tmp_path / "ui" / "src-tauri" / "target" / "debug"
    tauri_target.mkdir(parents=True)
    (tauri_target / "opencobalt-desktop").write_bytes(b"x" * (11 * 1024 * 1024))
    (tauri_target / "__global-api-script.js").write_text("~/cobaltos-vault leaked here")

    result = scan_directory(tmp_path)

    assert result.is_clean


def test_attachments_directory_is_skipped(tmp_path):
    folder = tmp_path / "attachments" / "att-1"
    folder.mkdir(parents=True)
    (folder / "notes.txt").write_text('password = "uploadedsecret"')
    result = scan_directory(tmp_path)
    assert result.is_clean


def test_secret_pattern_in_python_file(tmp_path):
    # Construct the credential line dynamically so the test file itself
    # does not trigger the scanner when the repo is scanned.
    key = "pass" + "word"
    val = "hunteR2secret"
    (tmp_path / "config.py").write_text(f'{key} = "{val}"\n')
    result = scan_directory(tmp_path)
    assert len(result.secret_hits) > 0
    assert not result.is_clean


def test_vault_path_reference_is_flagged(tmp_path):
    # Must be a real-looking path (~/cobaltos-vault), not just the word
    (tmp_path / "notes.md").write_text("All notes live at ~/cobaltos-vault on disk.")
    result = scan_directory(tmp_path)
    assert not result.is_clean
    assert any("vault" in issue.lower() for issue in result.issues)


def test_placeholder_secret_lines_are_allowed(tmp_path):
    key = "api" + "_key"
    (tmp_path / "README.md").write_text(f'{key} = "<placeholder>"\n')

    result = scan_directory(tmp_path)

    assert result.is_clean
    assert result.secret_hits == []


def test_docs_and_tests_skip_vault_path_scan_only(tmp_path):
    tests_dir = tmp_path / "tests"
    audits_dir = tmp_path / "docs" / "audits"
    tests_dir.mkdir()
    audits_dir.mkdir(parents=True)
    (tests_dir / "test_fixture.md").write_text("~/cobaltos-vault fixture path")
    (audits_dir / "note.md").write_text("/Users/colin/cobaltos-vault audit quote")
    key = "api" + "_key"
    (tmp_path / "docs" / "unsafe.md").write_text(f"{key}=supersecretvalue\n")

    result = scan_directory(tmp_path)

    assert not result.is_clean
    assert result.vault_path_hits == []
    assert result.secret_hits == ["docs/unsafe.md"]


def test_oversized_file_is_flagged(tmp_path):
    large_file = tmp_path / "big.txt"
    large_file.write_bytes(b"x" * (11 * 1024 * 1024))  # 11 MB
    result = scan_directory(tmp_path)
    assert len(result.oversized_files) > 0
    assert not result.is_clean


def test_summary_clean():
    result = ScanResult()
    assert result.summary() == "No public-safety issues detected."


def test_summary_lists_issue_count_and_messages():
    result = ScanResult(issues=["first issue", "second issue"])

    summary = result.summary()

    assert summary.startswith("2 issue(s) found:")
    assert "  - first issue" in summary
    assert "  - second issue" in summary
