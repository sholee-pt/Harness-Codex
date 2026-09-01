#!/usr/bin/env python3
"""Canonical change-discipline contracts emitted by Harness."""

from __future__ import annotations


PROJECT_BLOCK = """## Change discipline

For code-changing work:

- Surface material assumptions, conflicting interpretations, and simpler alternatives before editing.
- Implement the smallest change that satisfies the stated objective. Do not add speculative abstractions, configuration, or unrelated features.
- Limit edits to the requested responsibility and scope. Do not refactor, reformat, or clean up adjacent code unless the current change requires it. Remove only artifacts made obsolete by the current change.
- Define verification before implementation. Report completion only after the checks pass, or report the failure and remaining uncertainty explicitly."""

WRITER_BLOCK = """For code-changing work, follow the project-harness change discipline: surface material ambiguity and simpler alternatives before editing, make the smallest scoped change without adjacent cleanup, define verification before implementation, and report completion only after the checks pass."""


def normalize_line_endings(value: str) -> str:
    """Normalize only CRLF/CR to LF; all other content remains significant."""
    return value.replace("\r\n", "\n").replace("\r", "\n")


def require_exactly_once(value: str, canonical: str, label: str) -> None:
    normalized = normalize_line_endings(value)
    expected = normalize_line_endings(canonical)
    count = normalized.count(expected)
    if count != 1:
        raise ValueError(f"{label} must contain the canonical change-discipline contract exactly once")
