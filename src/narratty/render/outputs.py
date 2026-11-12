"""What the commands of a recording printed, compared with their ``expect_output``.

The asciicast recorder keeps the shell's output and notes where each typed line was
submitted with Enter and where the prompt came back. The output of a command is what
the shell printed in between, as plain text.
"""

from __future__ import annotations

import difflib
import functools
import re
from collections.abc import Sequence
from dataclasses import dataclass

from narratty.errors import OutputError
from narratty.render.cast import ESCAPE
from narratty.spec.model import Run, Spec

ELLIPSIS = "..."
MAX_DIFF_LINES = 20


@dataclass(frozen=True)
class Submitted:
    """A line typed at the prompt and what the shell printed after its Enter."""

    line: str
    output: str


@dataclass(frozen=True)
class Expected:
    scene_id: str
    command: str
    output: str


def captured(raw: str, enters: Sequence[tuple[str, int]], prompts: Sequence[int]) -> list[Submitted]:
    """The output after each Enter in ``raw``, up to the prompt or the next Enter.

    ``enters`` are the typed lines with the offset in ``raw`` where Enter was pressed;
    ``prompts`` the offsets where the prompt was back.
    """
    found = []
    for index, (line, start) in enumerate(enters):
        ends = [offset for offset in prompts if offset > start]
        if index + 1 < len(enters):
            ends.append(enters[index + 1][1])
        found.append(Submitted(line, raw[start : min(ends, default=len(raw))]))
    return found


# zsh's PROMPT_SP before each prompt: a mark (`%`, `#` for root), spaces to the end of the
# line and `\r \r`. After output without a final newline it moves the prompt to the next line.
_PROMPT_SP = re.compile(r"[%#]? {8,}\r \r")


def plain_lines(text: str, prompt: str) -> list[str]:
    """``text`` as the lines a reader sees: no escape sequences, the rest of the typed
    line and the prompt that follows the output left out."""
    lines = []
    for row in _PROMPT_SP.sub("\n", ESCAPE.sub("", text)).split("\n"):
        row = row.removesuffix("\r").rsplit("\r", 1)[-1]  # a lone \r redraws the line
        kept: list[str] = []
        for char in row:
            if char == "\b":
                kept = kept[:-1]
            elif char >= " " or char == "\t":
                kept.append(char)
        lines.append("".join(kept).expandtabs().rstrip())
    lines = lines[1:]  # the rest of the typed line, before its line break
    if lines and prompt.strip() and lines[-1].startswith(prompt.rstrip()):
        lines.pop()
    elif lines and prompt.strip() and lines[-1].endswith(prompt.rstrip()):
        lines[-1] = lines[-1].removesuffix(prompt.rstrip())  # output without a final newline
    while lines and not lines[-1]:
        lines.pop()
    while lines and not lines[0]:
        lines.pop(0)
    return lines


def expectations(spec: Spec) -> list[Expected]:
    """The ``run`` actions with an ``expect_output``, in order."""
    return [
        Expected(scene.id, action.run, action.expect_output)
        for scene in spec.scenes
        for action in scene.actions
        if isinstance(action, Run) and action.expect_output is not None
    ]


def matches(expected: Sequence[str], actual: Sequence[str]) -> bool:
    """Whether ``actual`` fits ``expected``: a line ``...`` stands for any lines (also
    none), ``...`` within a line for any text."""
    # A glob match over lines, with ``...`` as the star: iterative, so long outputs cannot
    # exhaust the recursion limit, and only the last ``...`` is ever backtracked to.
    i = j = 0
    star = -1  # the expected line of the last ``...`` seen
    resume = 0  # the actual line that ``...`` would take next
    while j < len(actual):
        if i < len(expected) and expected[i].strip() == ELLIPSIS:
            star, resume = i, j
            i += 1
        elif i < len(expected) and _line_fits(expected[i], actual[j]):
            i += 1
            j += 1
        elif star >= 0:
            resume += 1
            i, j = star + 1, resume
        else:
            return False
    while i < len(expected) and expected[i].strip() == ELLIPSIS:
        i += 1
    return i == len(expected)


def _line_fits(expected: str, actual: str) -> bool:
    if ELLIPSIS not in expected:
        return expected.rstrip() == actual
    return _line_pattern(expected.rstrip()).fullmatch(actual) is not None


@functools.lru_cache(maxsize=256)
def _line_pattern(expected: str) -> re.Pattern[str]:
    return re.compile(".*".join(re.escape(part) for part in expected.split(ELLIPSIS)))


def problems(spec: Spec, submitted: Sequence[Submitted]) -> list[str]:
    """A message for each command whose output differs from its ``expect_output``."""
    found = []
    position = 0
    for want in expectations(spec):
        last = want.command.split("\n")[-1].strip()
        index = next((i for i in range(position, len(submitted)) if submitted[i].line == last), None)
        where = f"scene {want.scene_id!r}: `{want.command}`"
        if index is None:
            found.append(f"{where} did not run at the shell prompt")
            continue
        position = index + 1
        expected = want.output.split("\n")
        actual = plain_lines(submitted[index].output, spec.terminal.prompt)
        if not matches(expected, actual):
            diff = list(difflib.unified_diff(expected, actual, "expected", "printed", lineterm="", n=2))
            if len(diff) > MAX_DIFF_LINES:
                diff = [*diff[:MAX_DIFF_LINES], "..."]
            found.append(f"{where} printed something else:\n" + "\n".join(f"    {row}" for row in diff))
    return found


def check(spec: Spec, submitted: Sequence[Submitted]) -> None:
    """Raise :class:`OutputError` when a command's output differs from its ``expect_output``."""
    found = problems(spec, submitted)
    if found:
        raise OutputError(
            "commands printed other output than expected:\n  " + "\n  ".join(found),
            hint="Fix the doc or the command. A line `...` in the expected output stands for any "
            'lines, `...` within a line for any text; `narratty="any-output"` on a block or '
            "`check_output: false` on the markdown entry turns the comparison off.",
        )
