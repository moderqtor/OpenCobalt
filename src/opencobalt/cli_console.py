"""Shared Rich console helpers for CLI output.

Rich freezes dumb or non-TTY sessions at 80 columns unless COLUMNS is honored
at render time. Pytest, CI, and pipes often have TERM=dumb, which previously
wrapped copy-paste packets and truncated copyable ids.
"""

from __future__ import annotations

import os

from rich.console import Console, ConsoleDimensions


class EnvWidthConsole(Console):
    """Honor COLUMNS on each render, including dumb terminals and captured stdout."""

    @property
    def size(self) -> ConsoleDimensions:
        base = super().size
        columns = os.environ.get("COLUMNS")
        if columns and columns.isdigit():
            return ConsoleDimensions(max(40, int(columns)), base.height)
        return base


def make_console(*, stderr: bool = False) -> EnvWidthConsole:
    return EnvWidthConsole(stderr=stderr, highlight=False)


def print_document(console: Console, text: str) -> None:
    """Write a copy-paste packet without Rich wrapping or truncation."""
    end = "" if text.endswith("\n") else "\n"
    console.file.write(text + end)
    console.file.flush()
