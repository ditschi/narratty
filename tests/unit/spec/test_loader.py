"""Loading specs from YAML, with positions in error messages."""

from __future__ import annotations

from pathlib import Path

import pytest

from narratty.errors import ExitCode
from narratty.spec import SpecError, load_spec
from narratty.spec.loader import parse_spec
from narratty.spec.template import TEMPLATE

FILE = Path("demo.narratty.yaml")


def _issues(text: str) -> list[str]:
    with pytest.raises(SpecError) as info:
        parse_spec(text, FILE)
    assert info.value.exit_code is ExitCode.VALIDATION
    return [issue.render(FILE) for issue in info.value.issues]


def test_template_is_valid() -> None:
    spec = parse_spec(TEMPLATE, FILE)
    assert [s.id for s in spec.scenes] == ["intro", "wrap"]


def test_folded_narration() -> None:
    text = "scenes:\n  - id: a\n    narration: >\n      one\n      two\n"
    assert parse_spec(text, FILE).scenes[0].narration == "one two"


def test_unknown_key_has_position_and_suggestion() -> None:
    text = "terminal:\n  widht: 10\nscenes:\n  - id: a\n"
    assert _issues(text) == [
        "demo.narratty.yaml:2:3: terminal.widht: unknown key 'widht' (did you mean 'width'?)"
    ]


def test_unknown_action_suggestion() -> None:
    text = "scenes:\n  - id: a\n    actions:\n      - type_comand: ls\n"
    assert _issues(text) == [
        "demo.narratty.yaml:4:9: scenes[0].actions[0]: "
        "unknown action 'type_comand' (did you mean 'type_command'?)"
    ]


def test_bad_hold_value() -> None:
    text = "scenes:\n  - id: a\n    actions:\n      - hold: fast\n"
    (issue,) = _issues(text)
    assert issue.startswith("demo.narratty.yaml:4:9: scenes[0].actions[0].hold: expected 'auto'")


def test_missing_scenes() -> None:
    assert _issues("meta:\n  title: x\n") == ["demo.narratty.yaml: scenes: missing required key 'scenes'"]


def test_yaml_syntax_error() -> None:
    (issue,) = _issues("scenes: [\n")
    assert issue.startswith("demo.narratty.yaml:2:1: invalid YAML")


def test_not_a_mapping() -> None:
    assert _issues("- a\n") == [
        "demo.narratty.yaml:1:1: the spec must be a YAML mapping with a 'scenes' list"
    ]


def test_several_problems_are_all_reported() -> None:
    text = "scenes:\n  - id: a\n    hiden: true\n  - id: B\n"
    assert len(_issues(text)) == 2


def test_load_spec_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SpecError, match="cannot read file"):
        load_spec(tmp_path / "nope.narratty.yaml")


def test_load_spec_reads_file(tmp_path: Path) -> None:
    path = tmp_path / "demo.narratty.yaml"
    path.write_text(TEMPLATE, encoding="utf-8")
    assert load_spec(path).meta.title == "My first narratty video"
