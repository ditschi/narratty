"""Warnings about a doc that expands fine but may not make the video its author expects.

``narratty validate`` prints them; they never fail. Each check reads the parsed blocks
of the selected sections together with the notes of :mod:`.scenes`, which say what
became of each block, so the rules for what is spoken or run live in one place.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterator
from pathlib import Path

from narratty.spec.markdown.parse import Block, Code, Comment, Heading, Text
from narratty.spec.markdown.scenes import (
    _COMMENT,
    Expansion,
    Note,
    _yaml_value,
    build_scenes,
    console_commands,
    select_sections,
)
from narratty.spec.markdown.shell import split_commands
from narratty.spec.model import MarkdownEntry, MarkdownNarration

SPATIAL = re.compile(
    r"(?<!\band )(?<!\bor )\b(click here|the following command|"
    r"(?:above|below)(?!\s+(?:it|them|this|that|the|a|an|its|their)\b))\b",
    re.IGNORECASE,
)
"""Words that point at the page; "and above" / "or below" (as in "level 2 and above") and
"below it" / "above the line" (a preposition with its object) are fine."""
ERROR_OUTPUT = re.compile(
    r"^\s*(?:(?:error|Error|ERROR)(?:\[\w+\])?(?:\s[\w ]{0,30})?:(?:\s|$)|ERROR\s|fatal:|panic:"
    r"|Traceback \(most recent call last\))"
)
BACKGROUND = re.compile(r"(?<![&|>])&\s*$")
"""A command sent to the background with ``&`` (not ``&&``, ``|&`` or ``>&``)."""
_FLOWCHART_KEYWORDS = {
    "flowchart",
    "graph",
    "subgraph",
    "end",
    "direction",
    "TB",
    "TD",
    "BT",
    "RL",
    "LR",
    "classDef",
    "class",
    "style",
    "linkStyle",
    "click",
}
_ID = re.compile(r"[A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)*")
_PARTICIPANT = re.compile(
    r"^\s*(?:create\s+)?(?:participant|actor)\s+(?P<id>\S+)(?:\s+as\s+(?P<label>.+?))?\s*$", re.MULTILINE
)
_MESSAGE = re.compile(r"^\s*(?P<a>[\w.@]+)\s*(?:<<)?--?(?:>>|>|x|\))[+-]?\s*(?P<b>[\w.@]+)\s*:", re.MULTILINE)
_BRACKETS = re.compile(r"\[[^\[\]]*\]|\([^()]*\)|\{[^{}]*\}")


PROMPT_LANGS = ("", "text", "txt", "shell-session", "terminal")
"""Languages whose `$ ` lines are likely commands; a `markdown` or `yaml` example is not."""


def lint(blocks: list[Block], entry: MarkdownEntry, path: Path, expansion: Expansion) -> list[Note]:
    """Warnings for the selected sections of a doc, in line order."""
    notes: dict[tuple[Path, int], list[str]] = {}
    for note in expansion.notes:
        notes.setdefault((note.file, note.line), []).append(note.what)
    selected = [
        block for start, end in select_sections(blocks, entry.sections) for block in blocks[start:end]
    ]
    found = [
        *_commands(path, expansion),
        *_blocks(selected, notes),
        *_left_out(selected, notes),
        *_background(selected, notes),
        *_focus(selected),
        *_spatial(selected, notes),
    ]
    return sorted(found, key=lambda note: (str(note.file), note.line))


def _warn(block: Block, message: str, line: int | None = None) -> Note:
    return Note(block.file, line or block.line, None, message)


def _commands(path: Path, expansion: Expansion) -> Iterator[Note]:
    if not any("command(s)" in note.what for note in expansion.notes):
        yield Note(
            path,
            1,
            None,
            "no command runs in the video; label command blocks `console` (with `$ ` prompts), "
            "`bash` or `sh`",
        )


def _blocks(selected: list[Block], notes: dict[tuple[Path, int], list[str]]) -> Iterator[Note]:
    for block in selected:
        whats = notes.get((block.file, block.line), [])
        if any(what == "table: not part of the video" for what in whats):
            yield _warn(
                block,
                "table left out of the video; a `table` comment speaks it row by row, a `slide` "
                "comment shows it (a `skip` comment silences this warning)",
            )
        if not isinstance(block, Code):
            continue
        if (
            block.lang in PROMPT_LANGS
            and any("left out (no" in what for what in whats)
            and any(line.startswith("$ ") for line in block.content.splitlines())
        ):
            yield _warn(
                block,
                "block left out, but its `$ ` lines look like commands; label it `console` to run "
                'them or add narratty="show" to show it',
            )
        if any(", run" in what for what in whats) and (line := _error_line(block)) is not None:
            shown = block.content.splitlines()[line].strip()
            yield _warn(
                block,
                f"the output shown looks like an error ({shown!r}); if the command is meant to fail, "
                'add narratty="expect-failure"',
                block.line + 1 + line,
            )


def _left_out(selected: list[Block], notes: dict[tuple[Path, int], list[str]]) -> Iterator[Note]:
    """Code blocks in a language that the video leaves out, in one warning."""
    left = [
        block
        for block in selected
        if isinstance(block, Code)
        and block.lang not in PROMPT_LANGS
        and any("left out (no title" in what for what in notes.get((block.file, block.line), []))
    ]
    if left:
        where = ", ".join(f"{block.lang} at line {block.line}" for block in left)
        count = f"{len(left)} code block{'s' if len(left) != 1 else ''}"
        yield _warn(
            left[0],
            f'{count} left out of the video ({where}); add narratty="show" to show one as a slide, '
            "or a title to write it to that file (a skip comment silences this for one block)",
        )


def _background(selected: list[Block], notes: dict[tuple[Path, int], list[str]]) -> Iterator[Note]:
    """Commands sent to the background whose output may arrive during later commands."""
    for block in selected:
        whats = notes.get((block.file, block.line), [])
        if not (isinstance(block, Code) and any(", run" in what for what in whats)):
            continue
        commands = (
            console_commands(block.content) if block.lang == "console" else split_commands(block.content)
        )
        for command in commands:
            text = command.text.strip()
            if BACKGROUND.search(text) and ">" not in text:
                yield _warn(
                    block,
                    f"{text!r} runs in the background and writes to the terminal; output that arrives "
                    "late lands in later commands and can break the build; redirect it, as in "
                    f"`{BACKGROUND.sub('', text).rstrip()} > server.log 2>&1 &`",
                    block.line + 1 + command.offset,
                )


def _error_line(block: Code) -> int | None:
    """Index of the first output line of a console block that looks like an error."""
    if block.lang != "console" or "expect-failure" in block.options:
        return None
    for index, line in enumerate(block.content.splitlines()):
        if not line.startswith(("$ ", "> ")) and ERROR_OUTPUT.match(line):
            return index
    return None


def _focus(selected: list[Block]) -> Iterator[Note]:
    """``focus`` ids that the diagram they apply to does not have."""
    diagram: Code | None = None
    pending: tuple[Comment, str] | None = None  # a slide comment's focus, for the next diagram
    for block in selected:
        if isinstance(block, Heading):
            diagram = pending = None
        elif isinstance(block, Code) and block.lang == "mermaid":
            diagram = block
            if pending is not None:
                yield from _check_focus(*pending, block)
            pending = None
        elif isinstance(block, Comment) and (match := _COMMENT.match(block.text)):
            kind, body = match["kind"], match["body"].strip()
            if kind == "focus" and diagram is not None:
                yield from _check_focus(block, body, diagram)
            elif kind == "slide" and "focus:" in body:
                options = _yaml_value(body, block, "slide")
                focus = options.get("focus") if isinstance(options, dict) else None
                pending = (block, str(focus)) if focus is not None else None


def _check_focus(comment: Comment, focus: str, diagram: Code) -> Iterator[Note]:
    targets = mermaid_targets(diagram.content)
    if targets is None:
        return
    kind, ids = targets
    if focus not in ids:
        what = "participant" if kind == "sequenceDiagram" else "node or subgraph"
        labels = {
            match["label"]: match["id"] for match in _PARTICIPANT.finditer(diagram.content) if match["label"]
        }
        match = difflib.get_close_matches(focus, sorted(ids), n=1)
        hint = f" (did you mean {match[0]!r}?)" if match else ""
        if kind == "sequenceDiagram" and focus in labels:
            hint = f" (did you mean {labels[focus]!r}? {focus} is its label, focus takes the id)"
        yield _warn(
            comment,
            f"focus {focus!r} is not a {what} of the Mermaid diagram at line {diagram.line}{hint}",
        )


def mermaid_targets(source: str) -> tuple[str, set[str]] | None:
    """The diagram type and the ids ``focus`` can name; None for types not checked.

    Generous on purpose: label words may count as ids, so a warning is never wrong.
    """
    text = re.sub(r"%%.*", "", source)
    text = re.sub(r"\A\s*---\n.*?\n---\n", "", text, flags=re.DOTALL)  # front matter
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    kind = lines[0].split()[0]
    body = "\n".join(lines[1:])
    if kind == "sequenceDiagram":
        ids = {match["id"] for match in _PARTICIPANT.finditer(body)}
        for match in _MESSAGE.finditer(body):
            ids |= {match["a"], match["b"]}
        return kind, ids
    if kind not in ("flowchart", "graph"):
        return None
    body = re.sub(r'"[^"]*"', "", body)
    body = re.sub(r"\|[^|\n]*\|", "", body)  # edge labels
    body = re.sub(r"@\{[^}]*\}", "", body)  # node@{ shape: … }
    body = re.sub(r":::[\w-]+", "", body)  # class shorthand
    while (shorter := _BRACKETS.sub(" ", body)) != body:
        body = shorter
    return kind, set(_ID.findall(body)) - _FLOWCHART_KEYWORDS


def _spatial(selected: list[Block], notes: dict[tuple[Path, int], list[str]]) -> Iterator[Note]:
    """Narration that points at the page: listeners cannot see "above" or "below"."""
    for block in selected:
        whats = notes.get((block.file, block.line), [])
        spoken = (
            isinstance(block, Text) and any(what.startswith("paragraph: spoken") for what in whats)
        ) or (isinstance(block, Comment) and "say comment: spoken" in whats)
        if not spoken:
            continue
        for match in SPATIAL.finditer(getattr(block, "text", "")):
            yield _warn(
                block,
                f"the narration says {match[1]!r}, which listeners cannot see; reword it so it works "
                "when heard (e.g. 'next', 'this command')",
            )


def lint_entry(entry: MarkdownEntry, path: Path, narration: MarkdownNarration) -> list[Note]:
    """Warnings about the doc for ``narratty validate``; none with ``lint: false``."""
    from narratty.spec.markdown.parse import parse_blocks
    from narratty.spec.markdown.source import read_source

    if not entry.lint:
        return []
    blocks = parse_blocks(read_source(path, entry.tabs))
    return lint(blocks, entry, path, build_scenes(blocks, entry, path, narration))
