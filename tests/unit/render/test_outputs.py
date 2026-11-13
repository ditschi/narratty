"""What commands printed, compared with their ``expect_output``."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from narratty.errors import OutputError
from narratty.render.cast import record
from narratty.render.outputs import Submitted, captured, check, matches, plain_lines, problems
from narratty.render.script import build_script
from narratty.spec.loader import parse_spec
from narratty.timeline import build_timeline


def test_captured_ends_at_the_prompt_or_the_next_enter() -> None:
    raw = "AAA\r\nout\r\n$ BBB\r\nmore\r\n$ "
    enters = [("AAA", 3), ("BBB", 15)]
    assert captured(raw, enters, prompts=[12]) == [
        Submitted("AAA", "\r\nout\r\n$ "),
        Submitted("BBB", "\r\nmore\r\n$ "),
    ]


def test_plain_lines() -> None:
    text = "ls\r\n\x1b[01;34mdir\x1b[0m  file\r\n10%\r100%\r\na\tb   \r\nab\bc\r\n\r\n$ "
    assert plain_lines(text, "$ ") == ["dir  file", "100%", "a       b", "ac"]


@pytest.mark.parametrize(
    ("expected", "actual", "fits"),
    [
        (["a", "b"], ["a", "b"], True),
        (["a", "b"], ["a"], False),
        (["a", "..."], ["a", "b", "c"], True),
        (["a", "...", "d"], ["a", "d"], True),
        (["a", "...", "d"], ["a", "b", "c"], False),
        (["v..."], ["v1.2.3"], True),
        (["v...!"], ["v1.2.3"], False),
        (["a.b"], ["axb"], False),
        ([], [], True),
    ],
)
def test_matches(expected: list[str], actual: list[str], fits: bool) -> None:
    assert matches(expected, actual) is fits


LONG = [f"line {n}" for n in range(5000)]


@pytest.mark.parametrize(
    ("expected", "actual", "fits"),
    [
        (["..."], ["x"] * 5000, True),
        (["a"] * 5000, ["a"] * 5000, True),
        (["a"] * 5000, ["a"] * 4999, False),
        (LONG, LONG, True),
        (["line 0", "...", "line 4999"], LONG, True),
        (["...", "line 2500", "...", "line 4999"], LONG, True),
        (["...", "line 2500", "...", "line 2499"], LONG, False),
        (["line ...", "..."] * 2500, LONG, True),
        (["...", "..."] * 50 + ["nope"], LONG, False),
    ],
)
def test_matches_long_output(expected: list[str], actual: list[str], fits: bool) -> None:
    assert matches(expected, actual) is fits


SPEC = """\
end_card: false
timing: {lead_in_ms: 0, tail_ms: 0}
terminal: {typing_speed_ms: 1}
scenes:
  - id: greet
    actions:
      - run: printf 'a\\nb\\n'
        expect_output: "a\\nb"
      - wait: {prompt: true}
      - run: echo two
        expect_output: one
      - wait: {prompt: true}
"""


def test_recorded_output_is_compared(tmp_path: Path) -> None:
    spec = parse_spec(SPEC, tmp_path / "t.narratty.yaml")
    recording = record(
        build_script(spec, build_timeline(spec, {})),
        terminal=spec.terminal,
        cwd=tmp_path,
        env={key: value for key, value in os.environ.items() if key != "PROMPT_COMMAND"},
        title="T",
        fast=True,
    )
    found = problems(spec, recording.submitted)
    assert len(found) == 1
    assert found[0].startswith("scene 'greet': `echo two` printed something else:")
    assert "-one" in found[0] and "+two" in found[0]
    with pytest.raises(OutputError):
        check(spec, recording.submitted)


def test_a_command_that_never_ran(tmp_path: Path) -> None:
    spec = parse_spec(SPEC, tmp_path / "t.narratty.yaml")
    assert problems(spec, [Submitted("printf 'a\\nb\\n'", "\r\na\r\nb\r\n$ ")]) == [
        "scene 'greet': `echo two` did not run at the shell prompt"
    ]


def test_plain_lines_drop_a_prompt_glued_to_the_output() -> None:
    assert plain_lines('printf x\r\n{"a":1}$ ', "$ ") == ['{"a":1}']


def test_plain_lines_drop_zsh_prompt_sp() -> None:
    mark = "\x1b[1m\x1b[7m%\x1b[27m\x1b[1m\x1b[0m" + " " * 79 + "\r \r\r\x1b[0m\x1b[J$ \x1b[K"
    assert plain_lines("echo hi\r\r\nhi\r\n" + mark, "$ ") == ["hi"]
    assert plain_lines('printf x\r\r\n{"a":1}' + mark, "$ ") == ['{"a":1}']
