"""Draft builds: estimated narration, smaller terminal."""

from __future__ import annotations

from pathlib import Path

import pytest

from narratty.build import plan
from narratty.draft import draft_spec, estimate_ms, estimated_audio_ms, speaking_rate
from narratty.spec.loader import parse_spec


def test_estimate_follows_length_and_rate() -> None:
    assert estimate_ms("x" * 14) == 1000
    assert estimate_ms("x" * 14, rate=2.0) == 500
    assert estimate_ms("  a   b  ") == estimate_ms("a b")


@pytest.mark.parametrize(
    ("tts", "rate"),
    [("{}", 1.0), ("{kokoro: {speed: 1.25}}", 1.25), ("{provider: piper, piper: {length_scale: 2.0}}", 0.5)],
)
def test_speaking_rate(tts: str, rate: float, tmp_path: Path) -> None:
    spec = parse_spec(f"tts: {tts}\nscenes: [{{id: a, narration: Hi.}}]\n", tmp_path / "s.narratty.yaml")
    assert speaking_rate(spec) == rate


def test_draft_spec_halves_the_terminal(tmp_path: Path) -> None:
    spec = parse_spec(
        "terminal: {width: 1200, height: 150, font_size: 11}\nscenes: [{id: a, narration: Hi.}, {id: b}]\n",
        tmp_path / "s.narratty.yaml",
    )
    term = draft_spec(spec).terminal
    assert (term.width, term.height, term.font_size) == (600, 100, 6)
    assert estimated_audio_ms(spec) == {"a": estimate_ms("Hi.")}


def test_draft_plan_skips_tts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_tts(*args: object) -> None:
        raise AssertionError("a draft must not load a TTS provider")

    monkeypatch.setattr("narratty.build.get_provider", no_tts)
    path = tmp_path / "s.narratty.yaml"
    path.write_text(
        "end_card: false\nscenes: [{id: a, narration: Hello there my friend.}]\n", encoding="utf-8"
    )
    planned = plan(path, draft=True)
    assert planned.draft and planned.clips == ()
    assert planned.timeline.scene("a").audio_ms == estimate_ms("Hello there my friend.")
    assert planned.spec.terminal.width == 600
