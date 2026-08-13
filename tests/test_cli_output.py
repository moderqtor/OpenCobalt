"""Semantic CLI output helpers and COLUMNS-aware console behavior."""

from __future__ import annotations

from opencobalt.cli_console import EnvWidthConsole, print_document
from tests.cli_output import assert_contains, first_match, semantic_text


def test_semantic_text_collapses_wrapped_lines() -> None:
    wrapped = "Treat this \ncontext as the source of continuity"
    assert semantic_text(wrapped) == (
        "Treat this context as the source of continuity"
    )
    assert_contains(wrapped, "Treat this context as the source of continuity")


def test_first_match_finds_id_after_wrap() -> None:
    output = "otrk-abc123def456  test\n                   gaps"
    assert first_match(r"(otrk-[0-9a-f]{6,})", output) == "otrk-abc123def456"


def test_console_honors_columns_when_term_is_dumb(monkeypatch) -> None:
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.delenv("COLUMNS", raising=False)
    narrow = EnvWidthConsole()
    assert narrow.width == 80
    monkeypatch.setenv("COLUMNS", "200")
    wide = EnvWidthConsole()
    assert wide.width == 200


def test_print_document_does_not_wrap(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.delenv("COLUMNS", raising=False)
    target = tmp_path / "out.txt"
    console = EnvWidthConsole(file=target.open("w", encoding="utf-8"))
    sentence = (
        "You are resuming OpenCobalt mission mis-000000000001 from durable "
        "mission memory."
    )
    print_document(console, sentence)
    console.file.close()
    written = target.read_text(encoding="utf-8")
    assert sentence in written
    assert "\n" not in written.strip()
