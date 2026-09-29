"""The narration track."""

from __future__ import annotations

from pathlib import Path

import pytest

from narratty.errors import RenderError
from narratty.render.narration import Placement, build_track
from narratty.tts.audio import wav_duration_ms
from tests.helpers import write_tone


def _nonsilent_ranges(path: Path) -> list[tuple[int, int]]:
    import wave
    from array import array

    with wave.open(str(path), "rb") as wav:
        rate = wav.getframerate()
        samples = array("h", wav.readframes(wav.getnframes()))
    ranges: list[tuple[int, int]] = []
    start = None
    step = rate // 100  # 10 ms windows
    for i in range(0, len(samples), step):
        loud = any(samples[i : i + step])
        ms = i * 1000 // rate
        if loud and start is None:
            start = ms
        if not loud and start is not None:
            ranges.append((start, ms))
            start = None
    if start is not None:
        ranges.append((start, len(samples) * 1000 // rate))
    return ranges


def test_clips_land_at_their_starts(tmp_path: Path) -> None:
    a = write_tone(tmp_path / "a.wav", 500)
    b = write_tone(tmp_path / "b.wav", 300)
    out = tmp_path / "track.wav"
    used = build_track([Placement("a", a, 200), Placement("b", b, 1500)], 3000, out)
    assert [p.start_ms for p in used] == [200, 1500]
    assert wav_duration_ms(out) == 3000
    ranges = _nonsilent_ranges(out)
    expected = [(200, 700), (1500, 1800)]
    assert len(ranges) == len(expected)
    for (start, end), (want_start, want_end) in zip(ranges, expected, strict=True):
        assert abs(start - want_start) <= 20 and abs(end - want_end) <= 20


def test_overlapping_clip_is_pushed_back(tmp_path: Path) -> None:
    a = write_tone(tmp_path / "a.wav", 1000)
    out = tmp_path / "track.wav"
    used = build_track([Placement("a", a, 0), Placement("b", a, 500)], 1500, out)
    assert [p.start_ms for p in used] == [0, 1000]
    assert wav_duration_ms(out) == 2000, "the track grows rather than cutting a clip"


def test_mixed_formats_are_rejected(tmp_path: Path) -> None:
    a = write_tone(tmp_path / "a.wav", 100, rate=22050)
    b = write_tone(tmp_path / "b.wav", 100, rate=24000)
    with pytest.raises(RenderError, match="different audio format"):
        build_track([Placement("a", a, 0), Placement("b", b, 500)], 1000, tmp_path / "t.wav")


def test_no_clips_gives_silence(tmp_path: Path) -> None:
    out = tmp_path / "t.wav"
    assert build_track([], 1200, out) == []
    assert wav_duration_ms(out) == 1200
