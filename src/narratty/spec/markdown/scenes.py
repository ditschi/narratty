"""Blocks of a Markdown doc to scenes: section selection, narration and actions."""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from narratty.spec.markdown import EntryError, ExpandedScene
from narratty.spec.markdown.parse import Block, Code, Heading, Text
from narratty.spec.model import MarkdownEntry, MarkdownNarration

SHELL_LANGS = ("bash", "sh", "shell")


def build_scenes(
    blocks: list[Block], entry: MarkdownEntry, path: Path, narration: MarkdownNarration
) -> list[ExpandedScene]:
    """The scenes of ``blocks`` for ``entry``, in the order of ``entry.sections``."""
    builder = _Builder(entry.id_prefix or id_part(path.stem) or "doc", narration, entry)
    for start, end in select_sections(blocks, entry.sections):
        builder.add(blocks[start:end])
    return builder.scenes


# ── sections ──────────────────────────────────────────────────────────────────


def select_sections(blocks: list[Block], sections: Sequence[str | list[str]] | None) -> list[tuple[int, int]]:
    """``(start, end)`` ranges of ``blocks`` for the selected sections, in their order."""
    if sections is None:
        return [(0, len(blocks))]
    headings = [index for index, block in enumerate(blocks) if isinstance(block, Heading)]
    ranges = []
    for number, selection in enumerate(sections):
        path = [selection] if isinstance(selection, str) else selection
        start = _find(blocks, headings, path, (number,))
        ranges.append((start, _section_end(blocks, start)))
    return ranges


def _section_end(blocks: list[Block], start: int) -> int:
    level = _heading(blocks[start]).level
    for index in range(start + 1, len(blocks)):
        block = blocks[index]
        if isinstance(block, Heading) and block.level <= level:
            return index
    return len(blocks)


def _find(blocks: list[Block], headings: list[int], path: list[str], loc: tuple[int | str, ...]) -> int:
    """The heading that ``path`` names, each part inside the previous one's section."""
    within = (0, len(blocks))
    found = -1
    for part in path:
        candidates = [index for index in headings if within[0] <= index < within[1] and index != found]
        matches = [i for i in candidates if _heading(blocks[i]).slug == part] or [
            i for i in candidates if _heading(blocks[i]).title.casefold() == part.casefold()
        ]
        if not matches:
            names = [_heading(blocks[i]).slug for i in candidates]
            suggestion = difflib.get_close_matches(part, names, n=1)
            hint = f" (did you mean {suggestion[0]!r}?)" if suggestion else ""
            raise EntryError(("sections", *loc), f"no section {part!r} in the doc{hint}")
        if len(matches) > 1 and part == path[-1]:
            lines = ", ".join(str(blocks[i].line) for i in matches)
            raise EntryError(
                ("sections", *loc),
                f"{part!r} names {len(matches)} headings (lines {lines}); "
                "pick one with a list path such as [parent, heading]",
            )
        found = matches[0]
        within = (found, _section_end(blocks, found))
    return found


def _heading(block: Block) -> Heading:
    assert isinstance(block, Heading)
    return block


# ── scenes ────────────────────────────────────────────────────────────────────


class _Builder:
    def __init__(self, prefix: str, narration: MarkdownNarration, entry: MarkdownEntry) -> None:
        self.prefix = prefix
        self.narration = narration
        self.defaults = entry.defaults.model_dump(exclude_none=True)
        self.scenes: list[ExpandedScene] = []
        self.section = ""
        self.count = 0
        self.pending: list[Text] = []

    def add(self, blocks: list[Block]) -> None:
        for block in blocks:
            if isinstance(block, Heading):
                self.flush()
                self.section, self.count = id_part(block.slug), 0
            elif isinstance(block, Text) and self.narration == "all":
                self.pending.append(block)
            elif isinstance(block, Code) and (actions := code_actions(block)):
                self.scene(block, actions)
        self.flush()

    def flush(self) -> None:
        """Narration after the last block of a section: a scene without actions."""
        if self.pending:
            self.scene(self.pending[0], [])

    def scene(self, block: Block, actions: list[dict[str, Any]]) -> None:
        data: dict[str, Any] = {"id": self.scene_id(block)}
        if self.pending:
            data["narration"] = " ".join(text.text for text in self.pending)
            self.pending = []
        if actions:
            data["actions"] = actions
        self.scenes.append(ExpandedScene({**data, **self.defaults}, block.file, block.line))

    def scene_id(self, block: Block) -> str:
        if isinstance(block, Code) and block.id:
            return f"{self.prefix}-{id_part(block.id)}"
        self.count += 1
        return "-".join(part for part in (self.prefix, self.section, str(self.count)) if part)


def code_actions(block: Code) -> list[dict[str, Any]]:
    """What the video does with a code block; empty when it is left out."""
    if block.lang == "console":
        commands = console_commands(block.content)
    elif block.lang in SHELL_LANGS:
        commands = shell_commands(block.content)
    else:
        return []
    return [action for command in commands for action in ({"run": command}, {"wait": {"prompt": True}})]


def console_commands(content: str) -> list[str]:
    """``$ `` lines of a console block, with their ``> `` continuation lines."""
    commands: list[str] = []
    for line in content.splitlines():
        if line.startswith("$ ") or line == "$":
            commands.append(line[2:])
        elif line.startswith("> ") and commands:
            commands[-1] += "\n" + line[2:]
    return [command for command in commands if command.strip()]


def shell_commands(content: str) -> list[str]:
    """One command per line; comments skipped, backslash continuations joined."""
    commands: list[str] = []
    continued = False
    for line in content.splitlines():
        if continued:
            commands[-1] += "\n" + line
        elif line.strip() and not line.lstrip().startswith("#"):
            commands.append(line)
        else:
            continue
        continued = line.endswith("\\")
    return commands


def id_part(text: str) -> str:
    """``text`` as part of a scene id: ASCII, lower case, ``-`` between words."""
    ascii_text = unicodedata.normalize("NFKD", text.replace("ß", "ss")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9_]+", "-", ascii_text.lower()).strip("-_")
