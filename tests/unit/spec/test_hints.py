"""Hints for valid but redundant spec lines."""

from __future__ import annotations

from pathlib import Path

import pytest

from narratty.spec.hints import find_hints, load_spec_with_hints
from narratty.spec.loader import parse_document
from narratty.spec.template import render_template

FILE = Path("demo.narratty.yaml")
RUN = "type_command followed by Enter can be written as `run: ...`"
END = "'hold: auto' has no effect at the end of a scene; leave it out"
AFTER = "'hold: auto' has no effect with narration_start: after_actions"
EXAMPLES = sorted((Path(__file__).parents[3] / "examples").glob("**/*.narratty.yaml"))


def _hints(text: str) -> list[str]:
    spec, data = parse_document(text, FILE)
    return [issue.render(FILE) for issue in find_hints(spec, data)]


def test_defaults_written_out() -> None:
    text = (
        "version: 1\n"
        "tts: {provider: piper, voice: en_US-lessac-medium}\n"
        "terminal:\n  width: 1200\n  height: 900\n  typing_speed_ms: 40ms\n"
        "scenes:\n  - id: a\n    hidden: false\n    actions: []\n"
    )
    assert _hints(text) == [
        "demo.narratty.yaml:2:24: tts.voice: same as the default; leave it out",
        "demo.narratty.yaml:4:3: terminal.width: same as the default; leave it out",
        "demo.narratty.yaml:6:3: terminal.typing_speed_ms: same as the default; leave it out",
        "demo.narratty.yaml:9:5: scenes[0].hidden: same as the default; leave it out",
        "demo.narratty.yaml:10:5: scenes[0].actions: same as the default; leave it out",
    ]


def test_actions_that_can_be_shorter() -> None:
    text = (
        "scenes:\n  - id: a\n    narration: Hi.\n    actions:\n"
        "      - type_command: ls\n"
        "      - enter\n"
        "      - wait: {screen: x}\n"
        "      - wait: {screen: y, timeout_ms: 15s}\n"
        "      - type_command: pwd\n"
        "      - key: enter\n"
        "      - hold: auto\n"
    )
    assert _hints(text) == [
        f"demo.narratty.yaml:5:9: scenes[0].actions[0]: {RUN}",
        "demo.narratty.yaml:6:9: scenes[0].actions[1]: write `key: Enter`",
        'demo.narratty.yaml:7:9: scenes[0].actions[2].wait: write `wait: "<pattern>"`',
        "demo.narratty.yaml:8:27: scenes[0].actions[3].wait.timeout_ms: same as the default; leave it out",
        f"demo.narratty.yaml:9:9: scenes[0].actions[4]: {RUN}",
        f"demo.narratty.yaml:11:9: scenes[0].actions[6]: {END}",
    ]


def test_hold_auto_mid_scene_is_fine_but_not_after_actions() -> None:
    body = "    actions:\n      - hold: auto\n      - run: ls\n"
    assert _hints(f"scenes:\n  - id: a\n    narration: Hi.\n{body}") == []
    assert _hints(f"scenes:\n  - id: a\n    narration: Hi.\n    narration_start: after_actions\n{body}") == [
        f"demo.narratty.yaml:6:9: scenes[0].actions[0]: {AFTER}"
    ]


@pytest.mark.parametrize(
    "text",
    [render_template("1.2.3"), *(path.read_text(encoding="utf-8") for path in EXAMPLES)],
    ids=["template", *(path.parent.name for path in EXAMPLES)],
)
def test_template_and_examples_have_no_hints(text: str) -> None:
    assert _hints(text) == []


def test_load_spec_with_hints(tmp_path: Path) -> None:
    path = tmp_path / "demo.narratty.yaml"
    path.write_text("scenes:\n  - id: a\n    actions: [enter]\n", encoding="utf-8")
    spec, hints = load_spec_with_hints(path)
    assert spec.scenes[0].id == "a"
    assert [hint.message for hint in hints] == ["write `key: Enter`"]
