"""Text normalization and WAV helpers."""

from __future__ import annotations

from pathlib import Path

from narratty.tts.audio import wav_duration_ms, write_wav
from narratty.tts.normalize import normalize_text
from tests.helpers import write_tone


def test_normalize_collapses_whitespace_and_typography() -> None:
    assert normalize_text("  It’s   “fast”…\n\tright? ") == 'It\'s "fast"... right?'


def test_normalize_is_idempotent() -> None:
    once = normalize_text("A — B")
    assert normalize_text(once) == once


def test_wav_duration(tmp_path: Path) -> None:
    assert wav_duration_ms(write_tone(tmp_path / "t.wav", 1250)) == 1250


def test_write_wav_from_plain_floats(tmp_path: Path) -> None:
    path = tmp_path / "out.wav"
    write_wav(path, [0.0, 0.5, -2.0, 2.0] * 6000, 24000)
    assert wav_duration_ms(path) == 1000
