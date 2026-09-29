"""Timeline math."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from narratty.spec.loader import parse_spec
from narratty.spec.model import Spec
from narratty.timeline import build_timeline


def _spec(body: str) -> Spec:
    return parse_spec(body, Path("t.narratty.yaml"))


SPEC = _spec(
    """\
timing: {narration_buffer_ms: 500, lead_in_ms: 300, tail_ms: 1000}
terminal: {typing_speed_ms: 40}
scenes:
  - id: setup
    hidden: true
    actions: [{type_command: "cd /tmp"}, enter]
  - id: short-actions
    narration: Long narration.
    actions: [{type_command: "ls"}, enter]
  - id: long-actions
    narration: Short.
    typing_speed_ms: 100
    actions: [{type_command: "0123456789"}, enter, {hold: 2000}]
  - id: keys
    actions: [{key: "Down 3"}, {ctrl_sequence: C-c}, {wait: {screen: done}}]
  - id: after
    narration: Afterwards.
    narration_start: after_actions
    actions: [{type_command: "pwd"}, enter]
"""
)
AUDIO = {"short-actions": 3000, "long-actions": 1000, "after": 1500}


def test_scene_lengths() -> None:
    timeline = build_timeline(SPEC, AUDIO)
    lengths = {s.scene_id: s.length_ms for s in timeline.scenes}
    assert lengths == {
        "setup": 0,
        "short-actions": 3500,  # narration + buffer beats 3 keys × 40 ms
        "long-actions": 3100,  # 11 keys × 100 ms + 2000 ms hold beats 1000 + 500
        "keys": 120,  # Down ×3 at 40 ms; ctrl and wait count as 0
        "after": 160 + 1500 + 500,
    }


def test_clip_starts_at_the_sum_of_previous_scenes() -> None:
    timeline = build_timeline(SPEC, AUDIO)
    visible = [s for s in timeline.scenes if not s.hidden]
    starts = [s.start_ms for s in visible]
    expected = [300 + sum(s.length_ms for s in visible[:i]) for i in range(len(visible))]
    assert starts == expected
    assert timeline.total_ms == 300 + sum(s.length_ms for s in visible) + 1000


def test_narration_offsets() -> None:
    timeline = build_timeline(SPEC, AUDIO)
    assert timeline.scene("short-actions").audio_start_ms == timeline.scene("short-actions").start_ms
    after = timeline.scene("after")
    assert after.audio_start_ms == after.start_ms + 160


@pytest.mark.parametrize(("actions_ms", "audio_ms"), list(itertools.product([0, 400, 5000], [0, 100, 4000])))
def test_no_scene_is_shorter_than_its_narration(actions_ms: int, audio_ms: int) -> None:
    hold = f"[{{hold: {actions_ms}}}]" if actions_ms else "[]"
    narration = "\n    narration: Words." if audio_ms else ""
    spec = _spec(f"scenes:\n  - id: s{narration}\n    actions: {hold}\n")
    scene = build_timeline(spec, {"s": audio_ms}).scenes[0]
    assert scene.length_ms >= actions_ms
    if audio_ms:
        assert scene.length_ms >= audio_ms + spec.timing.narration_buffer_ms
