"""Tape generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from narratty.render.tape import FONT_FAMILY, generate_tape, prompt_setup, quote_chunks
from narratty.spec.loader import parse_spec
from narratty.timeline import build_timeline

SPEC = """\
meta: {title: Demo}
terminal: {shell: zsh, prompt: "demo> ", theme: Nord, width: 800, height: 400, font_size: 18}
scenes:
  - id: setup
    hidden: true
    actions: [{type_command: "cd /srv"}, enter]
  - id: intro
    narration: Hello.
    actions:
      - type_command: "make build"
      - enter
      - hold: auto
      - wait: {screen: "built a/b", timeout_ms: 2000}
      - key: Down 2
      - ctrl_sequence: C-l
"""


def _tape(text: str = SPEC, audio: dict[str, int] | None = None) -> str:
    spec = parse_spec(text, Path("t.narratty.yaml"))
    return generate_tape(spec, build_timeline(spec, audio or {"intro": 2000}), Path("/out/v.mp4"))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ls -la", ['"ls -la"']),
        ('say "hi"', ["'say \"hi\"'"]),
        ('it\'s "x"', ['`it\'s "x"`']),
        ("a\"b'c`d", ["`a\"b'c`", '"`d"']),
    ],
)
def test_quote_chunks(text: str, expected: list[str]) -> None:
    chunks = quote_chunks(text)
    assert chunks == expected
    assert "".join(chunk[1:-1] for chunk in chunks) == text


def test_prompt_setup_per_shell() -> None:
    assert prompt_setup("bash", "it's> ") == "PS1='it'\\''s> '; clear"
    assert prompt_setup("fish", "$ ").startswith("function fish_prompt;")


def test_header_and_setup() -> None:
    lines = _tape().splitlines()
    assert lines[:10] == [
        '# narratty tape for "Demo"',
        'Output "/out/v.mp4"',
        "Set Shell zsh",
        "Set Width 800",
        "Set Height 400",
        "Set FontSize 18",
        f"Set FontFamily {json.dumps(FONT_FAMILY)}",
        'Set Theme "Nord"',
        "Set TypingSpeed 40ms",
        "Set Framerate 30",
    ]
    assert "Type@1ms \"PS1='demo> '; clear\"" in lines


def test_scenes() -> None:
    tape = _tape()
    hidden = tape.split("# scene: setup (hidden)\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert hidden[0] == "Hide" and hidden[-1] == "Show"
    assert 'Type@40ms "cd /srv"' in hidden
    intro = tape.split("# scene: intro\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert intro == [
        'Type@40ms "make build"',
        "Enter@40ms",
        "Sleep 1980ms",  # 2000 audio + 500 buffer - (10 chars + Enter + Down × 2) × 40 ms
        "Wait+Screen@2000ms /built a\\/b/",
        "Down@40ms 2",
        "Ctrl+L",
    ]


def test_fill_goes_last_without_hold_auto() -> None:
    tape = _tape(
        "scenes:\n  - id: a\n    narration: Hi.\n    actions: [{type_command: ls}, enter]\n", {"a": 1000}
    )
    scene = tape.split("# scene: a\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert scene == ['Type@40ms "ls"', "Enter@40ms", "Sleep 1380ms"]
    assert tape.endswith("Sleep 1000ms\n")


def test_run_types_presses_enter_and_holds() -> None:
    tape = _tape("timing: {run_hold_ms: 700}\nscenes:\n  - id: a\n    actions: [{run: ls}, {run: pwd}]\n")
    scene = tape.split("# scene: a\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert scene == [
        'Type@40ms "ls"',
        "Enter@40ms",
        "Sleep 700ms",
        'Type@40ms "pwd"',
        "Enter@40ms",
        "Sleep 700ms",
    ]


def test_tape_is_byte_stable() -> None:
    assert _tape() == _tape()


def _card_tape(end_card: str, python: str = "/opt/py 3/bin/python") -> str:
    spec = parse_spec(SPEC + f"end_card: {end_card}\n", Path("t.narratty.yaml"))
    return generate_tape(spec, build_timeline(spec, {"intro": 2000}), Path("/out/v.mp4"), python=python)


def test_end_card_is_drawn_hidden_and_then_held() -> None:
    tape = _card_tape("{enabled: true, duration_ms: 2500}")
    card = tape.split("# end card\n", 1)[1].splitlines()
    assert card[0] == "Hide"
    assert card[1] == "Type@1ms \"PS1=''; clear; '/opt/py 3/bin/python' -m narratty.end_card\""
    assert card[2:] == ["Enter@1ms", "Wait+Screen@30000ms /Created with narratty/", "Show", "Sleep 2500ms"]
    assert tape.index("Sleep 1000ms\n\n# end card") > 0, "after the tail"


def test_end_card_without_qr() -> None:
    assert "-m narratty.end_card --no-qr" in _card_tape("{enabled: true, qr: false}")


@pytest.mark.parametrize("end_card", ["false", "{duration_ms: 3000}"])
def test_no_end_card_unless_enabled(end_card: str) -> None:
    assert "end card" not in _card_tape(end_card)
