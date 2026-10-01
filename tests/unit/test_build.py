"""Pipeline glue: output names, clip placement and verification."""

from __future__ import annotations

from pathlib import Path

import pytest

from narratty.build import BuildResult, CastOutputs, Plan, default_output, place_clips, place_clips_at, verify
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


def test_place_clips_at_recorded_scene_starts(tmp_path: Path) -> None:
    assert [p.start_ms for p in place_clips_at(_plan(tmp_path), {"a": 10, "b": 2500})] == [10, 2500]


def test_cast_outputs_sit_beside_the_page() -> None:
    outputs = CastOutputs(Path("out/demo.html"))
    assert (outputs.cast, outputs.audio) == (Path("out/demo.cast"), Path("out/demo.mp3"))


def test_workspace_is_relative_to_the_spec(tmp_path: Path) -> None:
    assert _plan(tmp_path).workspace_source == tmp_path.resolve()


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


class FakeMedia:
    """VHS, ffprobe and ffmpeg replaced; records what mux was asked to do."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, video_ms: int) -> None:
        self.mux_kwargs: dict[str, object] = {}
        self.srt = ""
        monkeypatch.setattr("narratty.build.render_silent", self._render)
        monkeypatch.setattr(media, "probe", lambda path: media.MediaInfo(video_ms, True, True))
        monkeypatch.setattr(media, "mux", self._mux)

    @staticmethod
    def _render(planned: Plan, video: Path, work: Path, workspace: Path) -> None:
        video.write_bytes(b"mp4")

    def _mux(self, video: Path, audio: Path, out: Path, **kwargs: object) -> None:
        self.mux_kwargs = kwargs
        subtitles = kwargs.get("subtitles")
        if isinstance(subtitles, Path):
            self.srt = subtitles.read_text(encoding="utf-8")
        out.write_bytes(b"mp4")


DRAFT_SPEC = (
    "end_card: false\ntiming: {lead_in_ms: 0, tail_ms: 0}\nscenes: [{id: a, narration: Hello there.}]\n"
)


def test_draft_build_burns_in_the_narration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from narratty.build import WorkspaceOptions, build
    from narratty.draft import estimate_ms

    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text(DRAFT_SPEC, encoding="utf-8")
    planned_ms = estimate_ms("Hello there.") + 500
    fake = FakeMedia(monkeypatch, planned_ms)
    result = build(spec, draft=True, workspace=WorkspaceOptions("rw", allow_dirty=True))
    assert result.output == tmp_path / "demo.draft.mp4"
    assert fake.mux_kwargs == {"subtitles": fake.mux_kwargs["subtitles"], "burn": True, "fast": True}
    assert "Hello there." in fake.srt


def test_subtitle_files_show_the_spec_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from narratty.build import WorkspaceOptions, build
    from narratty.draft import estimate_ms

    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text(
        DRAFT_SPEC.replace("end_card: false", "end_card: false\nsubtitles: track"), encoding="utf-8"
    )
    fake = FakeMedia(monkeypatch, estimate_ms("Hello there.") + 500)
    build(spec, draft=True, subtitles="files", workspace=WorkspaceOptions("rw", allow_dirty=True))
    assert fake.mux_kwargs["subtitles"] is None
    vtt = (tmp_path / "demo.draft.vtt").read_text(encoding="utf-8")
    assert vtt.startswith("WEBVTT") and "Hello there." in vtt
    assert (tmp_path / "demo.draft.srt").is_file()


@pytest.mark.parametrize(("spec_mode", "override", "draft", "expected"), [
    ("none", None, False, "none"),
    ("track", None, False, "track"),
    ("track", None, True, "burn"),
    ("track", "files", True, "files"),
])  # fmt: skip
def test_subtitle_mode(
    spec_mode: str, override: str | None, draft: bool, expected: str, tmp_path: Path
) -> None:
    from dataclasses import replace

    from narratty.build import subtitle_mode

    planned = _plan(tmp_path)
    planned = replace(planned, spec=planned.spec.model_copy(update={"subtitles": spec_mode}), draft=draft)
    assert subtitle_mode(planned, override) == expected


def test_narrations_use_the_clip_lengths(tmp_path: Path) -> None:
    from narratty.build import narrations
    from narratty.render.subtitles import Narrated

    assert narrations(_plan(tmp_path), {"a": 0, "b": 2100}) == [
        Narrated("One.", 0, 1500),
        Narrated("Two.", 2100, 500),
    ]
