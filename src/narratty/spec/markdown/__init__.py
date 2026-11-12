"""Expand ``markdown`` scene entries into plain scenes.

The rules are in the design notes ("Markdown input"). The loader validates the entry,
checks that the file exists and validates the scenes returned here with the rest of the
spec, reporting their problems at the Markdown file and line.

The work is split in three passes: :mod:`.source` inserts snippets and picks content
tabs line by line, :mod:`.parse` turns the text into headings, text and code blocks, and
:mod:`.scenes` turns those into scenes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from narratty.spec.model import MarkdownEntry, MarkdownNarration

if TYPE_CHECKING:
    from narratty.spec.markdown.scenes import Expansion


@dataclass(frozen=True)
class ExpandedScene:
    """A raw scene mapping derived from a Markdown file, with where it came from."""

    data: dict[str, Any]
    file: Path
    line: int


class EntryError(Exception):
    """A problem with the entry's keys, reported at ``loc`` inside the entry in the YAML."""

    def __init__(self, loc: tuple[int | str, ...], message: str) -> None:
        super().__init__(message)
        self.loc = loc
        self.message = message


def expand_entry(entry: MarkdownEntry, path: Path, narration: MarkdownNarration) -> list[ExpandedScene]:
    """The scenes of the Markdown file at ``path`` for ``entry``, in order."""
    return explain_entry(entry, path, narration).scenes


def explain_entry(entry: MarkdownEntry, path: Path, narration: MarkdownNarration) -> Expansion:
    """The scenes for ``entry`` plus a note on what became of each part of the doc."""
    from narratty.spec.markdown.parse import parse_blocks
    from narratty.spec.markdown.scenes import build_scenes
    from narratty.spec.markdown.source import read_source

    blocks = parse_blocks(read_source(path, entry.tabs))
    return build_scenes(blocks, entry, path, narration)
