"""The asciicast recorder, with a real shell in a pseudo-terminal."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from narratty.errors import RenderError
from narratty.render.cast import ScreenText, ctrl_char, record, terminal_size
from narratty.render.script import build_script
from narratty.spec.loader import parse_spec
from narratty.spec.model import Terminal
from narratty.timeline import build_timeline

SPEC = """\
timing: {lead_in_ms: 100, tail_ms: 100, narration_buffer_ms: 0}
terminal: {typing_speed_ms: 5}
end_card: false
scenes:
  - id: setup
    hidden: true
    actions: [{type_command: "HIDDEN=secret; sleep 0.3"}, enter]
  - id: greet
    narration: Hello.
    actions:
      - type_command: "printf 'x%sy\\\\n' 42"
      - enter
      - wait: {screen: "x42y", timeout_ms: 3000}
"""


def _record(text: str, tmp_path: Path, audio_ms: int = 200) -> tuple[list[list[object]], dict[str, int], int]:
    spec = parse_spec(text, tmp_path / "t.narratty.yaml")
    timeline = build_timeline(spec, {"greet": audio_ms})
    recording = record(
        build_script(spec, timeline), terminal=spec.terminal, cwd=tmp_path, env=os.environ, title="T"
    )
    lines = recording.cast.splitlines()
    header = json.loads(lines[0])
    assert header["version"] == 2 and header["title"] == "T"
    assert (header["width"], header["height"]) == terminal_size(spec.terminal)
    return [json.loads(line) for line in lines[1:]], recording.scene_starts_ms, recording.duration_ms


def test_record_plays_the_script(tmp_path: Path) -> None:
    events, starts, duration = _record(SPEC, tmp_path)
    output = "".join(str(e[2]) for e in events if e[1] == "o")
    assert "x42y" in output
    assert ["m", "greet"] in [e[1:] for e in events], "visible scenes become markers"
    assert list(starts) == ["greet"]
    assert 100 <= starts["greet"] < 250, "hidden time is not recorded"
    assert float(str(events[-1][0])) * 1000 == pytest.approx(duration, abs=1), (
        "the last event sets the length"
    )
    times = [float(str(e[0])) for e in events]
    assert times == sorted(times)


def test_hidden_output_arrives_at_once(tmp_path: Path) -> None:
    events, _, _ = _record(SPEC, tmp_path)
    hidden = [e for e in events if "HIDDEN=secret" in str(e[2])]
    assert len(hidden) == 1, "hidden typing arrives in one event"
    assert "clear" in str(hidden[0][2]), "including the clear that ends the hidden scene"


def test_wait_times_out(tmp_path: Path) -> None:
    spec = SPEC.replace('screen: "x42y", timeout_ms: 3000', 'screen: "never", timeout_ms: 200')
    with pytest.raises(RenderError, match="/never/"):
        _record(spec, tmp_path)


def test_terminal_size_follows_pixels_and_font() -> None:
    assert terminal_size(Terminal()) == (81, 21)
    assert terminal_size(Terminal(width=1200, font_size=11)) == (163, 43)
    assert terminal_size(Terminal(width=100, height=100)) == (20, 5)


def test_ctrl_char() -> None:
    assert ctrl_char("C") == "\x03"
    assert ctrl_char("l") == "\x0c"


def test_screen_text_strips_escapes_and_follows_clears() -> None:
    screen = ScreenText(rows=2)
    screen.feed("old\r\n\x1b[H\x1b[2J\x1b[32mgreen\x1b[0m\x1b]0;title\x07\r\n")
    assert screen.text == "green\n"
    screen.feed("ab\bc\r\nlast")
    assert screen.text == "ac\nlast", "backspace erases, only the last rows count"


def test_timelapse_scene_is_sped_up_and_held_for_its_narration(tmp_path: Path) -> None:
    spec = parse_spec(
        """\
timing: {lead_in_ms: 0, tail_ms: 0, narration_buffer_ms: 0}
terminal: {typing_speed_ms: 1}
end_card: false
scenes:
  - id: start
    actions: [{type_command: "sleep 0.8; echo fin''ished"}, enter]
  - id: fast
    timelapse: 4
    narration: Sped up.
    actions: [{wait: {screen: "finished", timeout_ms: 5000}}]
  - id: next
    actions: [{hold: 50}]
""",
        tmp_path / "t.narratty.yaml",
    )
    timeline = build_timeline(spec, {"fast": 600})
    recording = record(
        build_script(spec, timeline), terminal=spec.terminal, cwd=tmp_path, env=os.environ, title="T"
    )
    starts = recording.scene_starts_ms
    assert starts["next"] - starts["fast"] == pytest.approx(600, abs=60), "held until the narration ends"
    assert recording.narration_offsets_ms == {"fast": 0}
    assert recording.duration_ms < 800, "0.8 s of waiting took about 0.2 s"
