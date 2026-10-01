"""Locating timelapse scenes in the VHS log and speeding them up."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from narratty.errors import RenderError
from narratty.render import timelapse
from narratty.render.media import LogLine
from narratty.render.timelapse import Segment, filter_graph, layout, marker_positions, remap
from narratty.spec.loader import parse_spec
from narratty.timeline import build_timeline

MARKS = Path("/w/marks")


def _log(*lines: tuple[float, str]) -> list[LogLine]:
    return [LogLine(at, text) for at, text in lines]


LOG = _log(
    (0.0, "File: t.tape"),
    (0.5, "[launcher.Browser] Download: chromium"),
    (1.0, "Output .mp4 /w/recording.mp4"),
    (1.0, "Set Shell bash"),
    (1.1, "Hide"),
    (1.9, "Show"),
    (2.0, f"Screenshot {MARKS}/scene-a.png"),
    (3.0, f"Screenshot {MARKS}/scene-b.png"),
    (4.0, "Hide"),
    (9.0, "Show"),
    (13.0, f"Screenshot {MARKS}/end-b.png"),
    (13.0, f"Screenshot {MARKS}/scene-c.png"),
    (13.0, "Screenshot /elsewhere/shot.png"),
    (14.9, "Creating /w/recording.mp4..."),
    (16.0, "Host your GIF on vhs.charm.sh"),
)


def test_markers_count_only_recorded_time() -> None:
    # Recorded: 1.9-4.0 and 9.0-14.9 = 8 s; a 7.6 s video scales everything by 0.95.
    positions = marker_positions(LOG, MARKS, 7600)
    assert positions == {"scene-a": 95, "scene-b": 1045, "end-b": 5795, "scene-c": 5795}


def test_no_markers() -> None:
    with pytest.raises(RenderError, match="no scene markers"):
        marker_positions(_log((0.0, "Show"), (1.0, "Creating x")), MARKS, 1000)


def test_remap() -> None:
    segments = [Segment(1000, 9000, 4, 500), Segment(10000, 12000, 2, 0)]
    assert remap(500, segments) == 500
    assert remap(1000, segments) == 1000
    assert remap(5000, segments) == 2000
    assert remap(9000, segments) == 3500, "after the sped-up 2 s and the 0.5 s freeze"
    assert remap(10000, segments) == 4500
    assert remap(13000, segments) == 6500


SPEC = """\
timing: {narration_buffer_ms: 0, lead_in_ms: 0, tail_ms: 0}
end_card: false
scenes:
  - id: a
    narration: Start.
    actions: [{type_command: "make"}, enter]
  - id: b
    timelapse: 8
    narration: Long step.
    actions: [{wait: {screen: done, timeout_ms: 600000}}]
  - id: c
    narration: After.
    narration_start: after_actions
    actions: [{type_command: "ls"}, enter]
"""


def test_layout_places_scenes_in_the_final_video() -> None:
    spec = parse_spec(SPEC, Path("t.narratty.yaml"))
    timeline = build_timeline(spec, {"a": 1000, "b": 3000, "c": 500})
    result = layout(timeline, {"scene-a": 0, "scene-b": 1000, "end-b": 17000, "scene-c": 17000})
    assert result.segments == (Segment(1000, 17000, 8, 1000),), "2 s sped up, held 1 s for 3 s narration"
    assert result.scene_starts_ms == {"a": 0, "b": 1000, "c": 4000}
    assert result.narration_offsets_ms == {"a": 0, "b": 0, "c": timeline.scene("c").audio_offset_ms}
    planned_without_b = timeline.total_ms - timeline.scene("b").length_ms
    assert result.expected_ms(timeline) == planned_without_b + 3000


def test_layout_needs_every_marker() -> None:
    spec = parse_spec(SPEC, Path("t.narratty.yaml"))
    with pytest.raises(RenderError, match="end-b"):
        layout(build_timeline(spec, {}), {"scene-a": 0, "scene-b": 1000, "scene-c": 2000})


def test_filter_graph() -> None:
    graph = filter_graph([Segment(1000, 9000, 4, 500)])
    assert graph == (
        "[0:v]split=3[s0][s1][s2];"
        "[s0]trim=start=0.0:end=1.0,setpts=PTS-STARTPTS[v0];"
        "[s1]trim=start=1.0:end=9.0,setpts=(PTS-STARTPTS)/4,fps=30,"
        "tpad=stop_mode=clone:stop_duration=0.5[v1];"
        "[s2]trim=start=9.0,setpts=PTS-STARTPTS[v2];"
        "[v0][v1][v2]concat=n=3:v=1:a=0[out]"
    )
    at_start = filter_graph([Segment(0, 2000, 2, 0)])
    assert at_start.startswith("[0:v]split=2[s0][s1];[s0]trim=start=0.0:end=2.0,setpts=(PTS-STARTPTS)/2")


def test_speed_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timelapse, "require", lambda tool: tool)
    calls: list[list[str]] = []

    def runner(argv: Sequence[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 1 if len(calls) > 1 else 0, "", "bad filter")

    timelapse.speed_up(tmp_path / "in.mp4", [Segment(0, 1000, 2, 0)], tmp_path / "out.mp4", runner=runner)
    assert calls[0][calls[0].index("-map") + 1] == "[out]"
    with pytest.raises(RenderError, match="bad filter"):
        timelapse.speed_up(tmp_path / "in.mp4", [], tmp_path / "out.mp4", runner=runner)
