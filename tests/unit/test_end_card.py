"""The closing card: when it is shown and how it is drawn."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
import segno

from narratty.end_card import (
    CREDIT,
    DOCS_URL,
    compose,
    container_flag,
    default_enabled,
    is_enabled,
    main,
    qr_lines,
    qr_size,
    with_end_card,
)
from narratty.errors import UsageError
from narratty.spec.model import Spec

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_CELL = re.compile(r"\x1b\[38;2;(\d+);\d+;\d+;48;2;(\d+);\d+;\d+m|▀")


def _spec(**end_card: object) -> Spec:
    return Spec.model_validate({"end_card": end_card, "scenes": [{"id": "a"}]})


def _config(tmp_path: Path, text: str) -> Path:
    directory = tmp_path / "config"
    directory.mkdir(exist_ok=True)
    (directory / "config.toml").write_text(text, encoding="utf-8")
    return directory


def test_on_by_default(tmp_path: Path) -> None:
    assert default_enabled(tmp_path / "missing") is True
    assert is_enabled(_spec(), directory=tmp_path / "missing") is True


def test_config_turns_it_off(tmp_path: Path) -> None:
    directory = _config(tmp_path, "[end_card]\nenabled = false\n")
    assert default_enabled(directory) is False
    assert is_enabled(_spec(), directory=directory) is False


def test_config_must_be_a_boolean(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="enabled must be true or false"):
        default_enabled(_config(tmp_path, '[end_card]\nenabled = "no"\n'))


@pytest.mark.parametrize(
    ("flag", "in_spec", "in_config", "expected"),
    [
        (None, None, False, False),
        (None, True, False, True),
        (None, False, True, False),
        (True, False, False, True),
        (False, True, True, False),
    ],
)
def test_flag_beats_spec_beats_config(
    tmp_path: Path, flag: bool | None, in_spec: bool | None, in_config: bool, expected: bool
) -> None:
    directory = _config(tmp_path, f"[end_card]\nenabled = {str(in_config).lower()}\n")
    assert is_enabled(_spec(enabled=in_spec), flag, directory) is expected


def test_with_end_card_resolves_the_spec() -> None:
    spec = with_end_card(_spec(duration_ms=2500), False)
    assert spec.end_card.enabled is False
    assert spec.end_card.duration_ms == 2500


def test_container_flag_carries_the_host_decision(tmp_path: Path) -> None:
    path = tmp_path / "demo.narratty.yaml"
    path.write_text("scenes: [{id: a}]\n", encoding="utf-8")
    assert container_flag(path, None) == "--end-card"
    assert container_flag(path, False) == "--no-end-card"
    _config(tmp_path, "[end_card]\nenabled = false\n")  # the unit conftest points here
    assert container_flag(path, None) == "--no-end-card"


def _modules(lines: list[str]) -> list[list[bool]]:
    """Decode the half-block rendering back into rows of dark modules."""
    rows: list[list[bool]] = []
    for line in lines:
        top: list[bool] = []
        bottom: list[bool] = []
        colors = ("255", "255")
        for match in _CELL.finditer(line):
            if match.group(0) == "▀":
                top.append(colors[0] == "0")
                bottom.append(colors[1] == "0")
            else:
                colors = (match.group(1), match.group(2))
        rows += [top, bottom]
    return rows


def test_qr_lines_encode_the_url() -> None:
    expected = [[bool(m) for m in row] for row in segno.make(DOCS_URL, error="m").matrix_iter(border=2)]
    decoded = _modules(qr_lines(DOCS_URL))
    assert decoded[: len(expected)] == expected
    assert all(not any(row) for row in decoded[len(expected) :]), "padding row is light"
    width, height = qr_size(DOCS_URL)
    assert (width, height) == (len(expected[0]), len(qr_lines(DOCS_URL)))


def _screen(text: str) -> list[str]:
    return _ANSI.sub("", text).split("\n")


def test_qr_beside_the_text_on_a_wide_terminal() -> None:
    lines = _screen(compose(100, 24))
    credit = next(line for line in lines if CREDIT in line)
    assert "▀" in credit, "the text sits on the QR code's rows"
    assert any(DOCS_URL in line for line in lines)
    assert len(lines) <= 24 and all(len(line) <= 100 for line in lines)


def test_qr_above_the_text_on_a_narrow_terminal() -> None:
    lines = _screen(compose(40, 30))
    credit = lines.index(next(line for line in lines if CREDIT in line))
    assert "▀" in lines[credit - 2] and "▀" not in lines[credit]
    assert len(lines) <= 30 and all(len(line) <= 40 for line in lines)


@pytest.mark.parametrize(("cols", "rows", "qr"), [(40, 10, True), (100, 24, False)])
def test_text_only_when_the_qr_does_not_fit_or_is_off(cols: int, rows: int, qr: bool) -> None:
    text = compose(cols, rows, qr=qr)
    assert "▀" not in text
    lines = _screen(text)
    assert any(line.strip() == CREDIT for line in lines)
    assert len(lines) <= rows


def test_text_is_centered() -> None:
    lines = _screen(compose(80, 11, qr=False))
    assert lines[:4] == ["", "", "", ""]
    credit = next(line for line in lines if CREDIT in line)
    assert credit.index(CREDIT) == (80 - len(DOCS_URL)) // 2


def test_main_draws_for_the_terminal_size(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("shutil.get_terminal_size", lambda: os.terminal_size((40, 10)))
    main(["https://example.org/", "--no-qr"])
    output = capsys.readouterr().out
    assert "https://example.org/" in output and CREDIT in output
    assert output.endswith("\x1b[?25l"), "the cursor is hidden"
