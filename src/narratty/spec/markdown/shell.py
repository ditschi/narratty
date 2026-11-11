"""Shell code from a doc's code blocks, split into the commands the video types.

A command ends where the shell would run it: outside quotes, heredocs and compound
commands (``if … fi``, ``for … done``, ``{ … }``), and not after a trailing ``\\``,
``|``, ``&&`` or ``||``. Comments are not typed. This is a scanner, not a shell
parser; it errs on the side of keeping lines together.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_OPENERS = {"if", "case", "for", "while", "until", "select", "{"}
_CLOSERS = {"fi", "esac", "done", "}"}
# Words after which the next word is in command position again.
_COMMAND_START = {"", ";", "&", "|", "&&", "||", "(", ")", "{", "then", "do", "else", "elif", "!", "in"}
_HEREDOC = re.compile(r"<<(-?)[ \t]*(['\"]?)([A-Za-z_][\w-]*)\2")
_PLACEHOLDER = re.compile(r"<([A-Za-z][\w.-]*)>")
_CONTINUES = ("\\", "|", "&&", "||")


@dataclass
class Command:
    """One command as typed, with its first line's offset in the block (0-based)."""

    text: str
    offset: int
    placeholders: list[str] = field(default_factory=list)
    """``<name>`` found outside single quotes and heredoc bodies."""


@dataclass
class _State:
    quote: str | None = None
    depth: int = 0
    parens: int = 0
    case: int = 0
    heredocs: list[tuple[str, bool]] = field(default_factory=list)
    previous: str = ""

    @property
    def open(self) -> bool:
        return bool(self.quote or self.depth > 0 or self.parens > 0 or self.heredocs)


def split_commands(content: str) -> list[Command]:
    """The commands of a ``bash``/``sh`` block, in order."""
    commands: list[Command] = []
    current: Command | None = None
    state = _State()
    for offset, line in enumerate(content.splitlines()):
        if state.heredocs and not state.quote:
            assert current is not None
            current.text += "\n" + line
            delimiter, strip_tabs = state.heredocs[0]
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                state.heredocs.pop(0)
        else:
            placeholders = current.placeholders if current else []
            code = _scan(line, state, placeholders)
            if current is None:
                if not code.strip():
                    continue
                current = Command(code, offset, placeholders)
            elif code.strip() or state.quote:
                current.text += "\n" + code
        if current is not None and not state.open and not current.text.rstrip().endswith(_CONTINUES):
            commands.append(current)
            current, state = None, _State()
    if current is not None:
        commands.append(current)
    return commands


def clean_command(command: str) -> Command:
    """A single command (a ``console`` line) without its trailing comment."""
    commands = split_commands(command)
    if not commands:
        return Command("", 0)
    first = commands[0]
    for more in commands[1:]:
        first.text += "\n" + more.text
        first.placeholders += more.placeholders
    return first


def _scan(line: str, state: _State, placeholders: list[str]) -> str:
    """``line`` without its comment, updating ``state`` (quotes, keywords, heredocs)."""
    out: list[str] = []
    word = ""
    index = 0
    state.previous = ""  # every line starts in command position
    while index < len(line):
        char = line[index]
        if state.quote:
            taken = _quoted(line, index, state, placeholders)
            out.append(line[index : index + taken])
            index += taken
            continue
        if char == "#" and not word and (not out or out[-1][-1:] in " \t;&|("):
            break  # a comment runs to the end of the line
        if char == "\\" or char == "<":
            taken = 2 if char == "\\" else _angle(line, index, state, placeholders)
            out.append(line[index : index + taken])
            word += line[index + 1 : index + taken] if char == "\\" else line[index : index + taken]
            index += taken
            continue
        if char in " \t;&|()":
            _word(word, state)
            word = ""
            _operator(char, state)
        else:
            state.quote = char if char in "'\"" else None
            word += char
        out.append(char)
        index += 1
    _word(word, state)
    return "".join(out).rstrip()


def _quoted(line: str, index: int, state: _State, placeholders: list[str]) -> int:
    """Characters taken at ``index`` inside quotes; closes the quote at its end."""
    char = line[index]
    if state.quote == '"':
        if char == "\\":
            return 2
        if char == "<" and (placeholder := _PLACEHOLDER.match(line, index)):
            placeholders.append(placeholder[0])
    if char == state.quote:
        state.quote = None
    return 1


def _angle(line: str, index: int, state: _State, placeholders: list[str]) -> int:
    """Characters taken by a ``<`` outside quotes: a heredoc operator, or just the ``<``."""
    here_string = "<" in (line[index - 1 : index], line[index + 2 : index + 3])
    if not here_string and (heredoc := _HEREDOC.match(line, index)):
        state.heredocs.append((heredoc[3], heredoc[1] == "-"))
        return len(heredoc[0])
    if line[index - 1 : index] != "<" and (placeholder := _PLACEHOLDER.match(line, index)):
        placeholders.append(placeholder[0])
    return 1


def _word(word: str, state: _State) -> None:
    if not word:
        return
    if state.previous in _COMMAND_START:
        if word in _OPENERS:
            state.depth += 1
            state.case += word == "case"
        elif word in _CLOSERS and state.depth:
            state.depth -= 1
            state.case -= word == "esac" and state.case > 0
    state.previous = word


def _operator(char: str, state: _State) -> None:
    if char in " \t":
        return
    if char == "(" and not state.case:
        state.parens += 1
    elif char == ")" and not state.case and state.parens:
        state.parens -= 1
    state.previous = char
