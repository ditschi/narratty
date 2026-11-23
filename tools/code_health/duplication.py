"""Duplicated code (DRY): runs of identical normalised lines found elsewhere.

Like pylint's similarity checker: blank lines, comments, docstrings, imports and
lines holding only brackets are ignored, the rest is compared after stripping.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .config import Config
from .model import Smell
from .source import Source

_TRIVIAL = re.compile(r"^[\s()\[\]{},:;]*$")
_IMPORT = re.compile(r"^(import|from)\s")

Location = tuple[str, int]  # (path, index into the normalised lines)


def normalised(source: Source) -> list[tuple[int, str]]:
    """``(line number, stripped text)`` of the lines that take part in the comparison."""
    lines = source.text.splitlines()
    kept = []
    for number in sorted(source.code_lines):
        text = lines[number - 1].strip()
        if not _TRIVIAL.match(text) and not _IMPORT.match(text):
            kept.append((number, text))
    return kept


def duplication_smells(sources: list[Source], config: Config) -> dict[str, list[Smell]]:
    """Duplicated blocks per file path."""
    rule = config.rule("duplication")
    size = int(rule.threshold)
    lines = {source.path: normalised(source) for source in sources}
    marked, partner = _mark_duplicates(lines, size)
    smells: dict[str, list[Smell]] = defaultdict(list)
    for path, indices in marked.items():
        for start, length in _blocks(sorted(indices)):
            other_path, other_index = partner[(path, start)]
            other_line = lines[other_path][other_index][0]
            message = f"{length} lines duplicated in {other_path}:{other_line}"
            line = lines[path][start][0]
            smells[path].append(
                Smell("duplication", line, "<block>", length, message, rule.deduction(length))
            )
    return smells


def _mark_duplicates(
    lines: dict[str, list[tuple[int, str]]], size: int
) -> tuple[dict[str, set[int]], dict[Location, Location]]:
    marked: dict[str, set[int]] = defaultdict(set)
    partner: dict[Location, Location] = {}
    for locations in _windows(lines, size).values():
        for here, there in _pairs(locations, size):
            marked[here[0]].update(range(here[1], here[1] + size))
            partner.setdefault(here, there)
    return marked, partner


def _windows(lines: dict[str, list[tuple[int, str]]], size: int) -> dict[tuple[str, ...], list[Location]]:
    """Where each run of ``size`` normalised lines occurs."""
    windows: dict[tuple[str, ...], list[Location]] = defaultdict(list)
    for path, kept in lines.items():
        texts = [text for _, text in kept]
        for start in range(len(texts) - size + 1):
            windows[tuple(texts[start : start + size])].append((path, start))
    return windows


def _pairs(locations: list[Location], size: int) -> list[tuple[Location, Location]]:
    """Each location with one other, non-overlapping location of the same window."""
    pairs = []
    for here in locations:
        others = [there for there in locations if not _overlaps(here, there, size)]
        if others:
            pairs.append((here, others[0]))
    return pairs


def _overlaps(here: Location, there: Location, size: int) -> bool:
    return here[0] == there[0] and abs(here[1] - there[1]) < size


def _blocks(indices: list[int]) -> list[tuple[int, int]]:
    """``(start, length)`` of each run of consecutive indices."""
    blocks: list[tuple[int, int]] = []
    for index in indices:
        if blocks and blocks[-1][0] + blocks[-1][1] == index:
            blocks[-1] = (blocks[-1][0], blocks[-1][1] + 1)
        else:
            blocks.append((index, 1))
    return blocks
