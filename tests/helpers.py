"""Shared test helpers."""

from __future__ import annotations

import re

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    """Strip ANSI styling (Typer forces colour on GitHub Actions)."""
    return _ANSI.sub("", text)
