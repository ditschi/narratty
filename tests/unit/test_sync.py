"""Per-scene alignment of the narration to the recorded markers."""

from __future__ import annotations

from pathlib import Path

import pytest

from narratty.render.script import Cue, Sleep, build_script, narration_cue
from narratty.spec.loader import parse_spec
from narratty.spec.model import Spec
from narratty.sync import (
    Overrun,
    linear_starts,
    narration_starts,
    overruns,
    retime_factor,
    scene_ends,
    too_far,
)
from narratty.timeline import Timeline, build_timeline


def _spec(body: str) -> Spec:
    return parse_spec(body, Path("t.narratty.yaml"))


SPEC = _spec(
    """\
end_card: false
timing: {narration_buffer_ms: 500, lead_in_ms: 0, tail_ms: 0, run_hold_ms: 0}
terminal: {typing_speed_ms: 100}
scenes:
  - id: setup
    hidden: true
    actions: [{run: "cd /tmp"}]
  - id: talk
    narration: Run, then explain.
    actions: [{run: "ls"}, {hold: auto}]
  - id: after
    narration: Afterwards.
    narration_start: after_actions
    actions: [{run: "make"}]
  - id: quiet
    actions: [{hold: 1000}]
"""
)
AUDIO = {"talk": 3000, "after": 2000}


def _timeline() -> Timeline:
    return build_timeline(SPEC, AUDIO)


def test_planned_positions_without_slow_commands() -> None:
    timeline = _timeline()
    # talk: 3500 (narration + buffer), after: 500 typing + 2500 fill, quiet: 1000
    assert [(t.scene_id, t.start_ms, t.length_ms) for t in timeline.scenes] == [
        ("setup", 0, 0),
        ("talk", 0, 3500),
        ("after", 3500, 3000),
        ("quiet", 6500, 1000),
    ]


def test_narration_follows_each_scene_s_recorded_start() -> None:
    # A slow `ls` made talk 2 s longer; the narration of after still starts with its scene.
    recorded = {"talk": 0, "after": 5500, "quiet": 8500}
    assert narration_starts(_timeline(), recorded) == {"talk": 0, "after": 6000, "quiet": 8500}


def test_after_actions_narration_starts_at_its_recorded_cue() -> None:
    recorded = {"talk": 0, "after": 3500, "quiet": 9000}
    cues = {narration_cue("after"): 6500}  # make took 2.5 s longer than typed
    assert narration_starts(_timeline(), recorded, cues)["after"] == 6500


def test_offsets_override_the_planned_offset() -> None:
    starts = narration_starts(_timeline(), {"talk": 100, "after": 3600}, offsets={"after": 0})
    assert starts == {"talk": 100, "after": 3600}


def test_linear_starts_stretch_the_plan() -> None:
    assert linear_starts(_timeline(), 15000) == {"talk": 0, "after": 8000, "quiet": 13000}


def test_scene_ends_are_the_next_visible_start() -> None:
    assert scene_ends(_timeline(), {"talk": 0, "after": 3500, "quiet": 6500}, 7500) == {
        "talk": 3500,
        "after": 6500,
        "quiet": 7500,
    }


def test_no_overrun_when_the_scenes_fit() -> None:
    starts = {"talk": 0, "after": 3500, "quiet": 6500}
    wanted = narration_starts(_timeline(), starts)
    assert overruns(_timeline(), starts, 7500, wanted, wanted) == []


def test_a_scene_recorded_shorter_than_planned_clips_its_narration() -> None:
    # Dropped frames: talk lasted 2.5 s in the video instead of 3.5 s.
    starts = {"talk": 0, "after": 2500, "quiet": 5500}
    wanted = narration_starts(_timeline(), starts)
    [found] = overruns(_timeline(), starts, 6500, wanted, wanted)
    assert found == Overrun("talk", 500, 3000, 3500, 2500)
    assert found.describe() == "talk (0.50s over: scene recorded 1.00s shorter than planned)"
    assert too_far([found], 0.10) == [found]
    assert too_far([found], 0.20) == []


def test_a_clip_pushed_back_by_the_one_before_says_so() -> None:
    starts = {"talk": 0, "after": 3500, "quiet": 5000}
    wanted = {"talk": 0, "after": 4000}
    placed = {"talk": 0, "after": 4800}
    [found] = overruns(_timeline(), starts, 6000, placed, wanted)
    assert found.scene_id == "after" and found.pushed_ms == 800
    assert "late after the previous narration" in found.cause


@pytest.mark.parametrize(
    ("video", "recorded", "expected"),
    [
        (10000, 10000, None),
        (9800, 10000, None),  # within VHS's usual few percent
        (8000, 10000, 1.25),
        (9500, 10000, 10000 / 9500),
        (9400, 9800, None),  # 4%, but only 400 ms: VHS's start and stop overhead
        (0, 10000, None),
        (10000, 0, None),
    ],
)
def test_retime_factor(video: int, recorded: int, expected: float | None) -> None:
    assert retime_factor(video, recorded) == expected


def test_script_marks_where_after_actions_narration_starts() -> None:
    steps = build_script(SPEC, _timeline())
    cue = steps.index(Cue(narration_cue("after")))
    assert isinstance(steps[cue + 1], Sleep) and steps[cue + 1].ms == 2500
    assert Cue(narration_cue("talk")) not in steps
