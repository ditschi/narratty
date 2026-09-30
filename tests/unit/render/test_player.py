"""The HTML page that plays a cast with its narration."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from narratty.render.player import PLAYER_VERSION, player_page, player_theme


@pytest.mark.parametrize(
    ("vhs", "expected"),
    [("Dracula", "dracula"), ("Solarized Dark", "solarized-dark"), ("Catppuccin Mocha", None)],
)
def test_player_theme(vhs: str, expected: str | None) -> None:
    assert player_theme(vhs) == expected


def test_page_embeds_cast_and_audio(tmp_path: Path) -> None:
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"ID3fake")
    cast = '{"version": 2}\n[0.1, "o", "</script><b>"]\n'
    page = player_page("A <demo>", cast, audio, theme="nord")
    assert "<title>A &lt;demo&gt;</title>" in page
    assert "</script><b>" not in page, "cast text cannot close the script element"
    assert "<\\/script><b>" in page
    assert "data:audio/mpeg;base64," + base64.b64encode(b"ID3fake").decode() in page
    assert '"theme": "nord"' in page
    assert f"asciinema-player@{PLAYER_VERSION}/" in page
    assert page.count('integrity="sha384-') == 2


def test_page_without_theme(tmp_path: Path) -> None:
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"")
    assert '"theme"' not in player_page("T", "{}", audio)
