"""Expand ``markdown`` scene entries into plain scenes.

The rules are in the design notes ("Markdown input"). The loader validates the entry,
checks that the file exists and validates the scenes returned here with the rest of the
spec, reporting their problems at the Markdown file and line.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from narratty.spec.loader import Issue, SpecError
from narratty.spec.model import MarkdownEntry, MarkdownNarration


@dataclass(frozen=True)
class ExpandedScene:
    """A raw scene mapping derived from a Markdown file, with where it came from."""

    data: dict[str, Any]
    file: Path
    line: int


def expand_entry(entry: MarkdownEntry, path: Path, narration: MarkdownNarration) -> list[ExpandedScene]:
    """The scenes of the Markdown file at ``path`` for ``entry``, in order."""
    raise SpecError(path, [Issue("", "Markdown input is not implemented yet", 1, 1, file=path)])
