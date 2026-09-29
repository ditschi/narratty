"""Pipeline glue: output names, clip placement and verification."""

from __future__ import annotations

from pathlib import Path

import pytest

from narratty.build import BuildResult, Plan, default_output, place_clips, verify
from narratty.errors import RenderError, SyncError
from narratty.render import media
from narratty.spec.loader import parse_spec
from narratty.timeline import build_timeline
from narratty.tts.synth import Clip


@pytest.mark.parametrize(
    ("spec", "suffix", "expected"),
    [
        ("d/demo.narratty.yaml", ".mp4", "d/demo.mp4"),
        ("demo.narratty.yml", ".silent.mp4", "demo.silent.mp4"),
        ("tour.yaml", ".mp4", "tour.mp4"),
        ("odd.txt", ".mp4", "odd.mp4"),
    ],
)
def test_default_output(spec: str, suffix: str, expected: str) -> None:
    assert default_output(Path(spec), suffix) == Path(expected)


def _plan(tmp_path: Path) -> Plan:
    spec = parse_spec(
        "timing: {lead_in_ms: 0, tail_ms: 0}\nscenes:\n"
        "  - id: a\n    narration: One.\n  - id: b\n    narration: Two.\n",
        tmp_path / "s.narratty.yaml",
    )
    clips = (Clip("a", tmp_path / "a.wav", 1500, False), Clip("b", tmp_path / "b.wav", 500, False))
    timeline = build_timeline(spec, {c.scene_id: c.duration_ms for c in clips})
    return Plan(tmp_path / "s.narratty.yaml", spec, clips, timeline)


def test_place_clips_scales_with_the_rendered_length(tmp_path: Path) -> None:
    planned = _plan(tmp_path)
    assert planned.timeline.total_ms == 3000
    assert [p.start_ms for p in place_clips(planned, 3000)] == [0, 2000]
    assert [p.start_ms for p in place_clips(planned, 2940)] == [0, 1960]


def test_workspace_is_relative_to_the_spec(tmp_path: Path) -> None:
    assert _plan(tmp_path).workspace == tmp_path.resolve()


def _result(tmp_path: Path, video_ms: int) -> BuildResult:
    return BuildResult(tmp_path / "o.mp4", 10000, video_ms, ())


def test_verify_accepts_small_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(media, "probe", lambda path: media.MediaInfo(9700, True, True))
    verify(_result(tmp_path, 9700), max_drift=0.1)


def test_verify_rejects_large_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(media, "probe", lambda path: media.MediaInfo(13000, True, True))
    with pytest.raises(SyncError, match=r"\+30%"):
        verify(_result(tmp_path, 13000), max_drift=0.1)


def test_verify_needs_both_streams(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(media, "probe", lambda path: media.MediaInfo(10000, True, False))
    with pytest.raises(RenderError, match="audio stream"):
        verify(_result(tmp_path, 10000), max_drift=0.1)
