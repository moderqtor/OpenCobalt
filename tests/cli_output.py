"""CLI test helpers that assert command semantics, not Rich wrap layout."""

from __future__ import annotations

import re


def semantic_text(output: str) -> str:
    """Collapse wrap-induced whitespace while keeping words and punctuation."""
    return " ".join(output.replace("\u00a0", " ").split())


def contains_semantic(output: str, snippet: str) -> bool:
    return semantic_text(snippet) in semantic_text(output)


def assert_contains(output: str, snippet: str) -> None:
    if contains_semantic(output, snippet):
        return
    raise AssertionError(f"missing {snippet!r} in CLI output:\n{output}")


def first_match(pattern: str, output: str, group: int = 1) -> str:
    """Search raw output first, then whitespace-collapsed output."""
    for text in (output, semantic_text(output)):
        match = re.search(pattern, text)
        if match:
            return match.group(group)
    raise AssertionError(f"no match for {pattern} in output:\n{output}")
