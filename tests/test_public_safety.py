
from opencobalt.core.public_safety import scan_directory


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


def test_oversized_file_is_flagged(tmp_path):
    large_file = tmp_path / "big.txt"
    large_file.write_bytes(b"x" * (11 * 1024 * 1024))  # 11 MB
    result = scan_directory(tmp_path)
    assert len(result.oversized_files) > 0
    assert not result.is_clean


def test_summary_clean():
    class FakeResult:
        is_clean = True
        issues = []
        def summary(self): return "No public-safety issues detected."
    r = FakeResult()
    assert "No public-safety issues" in r.summary()
