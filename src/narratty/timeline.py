"""The timeline: when each scene starts and how long it lasts in the video.

Narration starts when its scene starts (or after the scene's actions with
``narration_start: after_actions``). A scene lasts
``max(action_ms, audio_ms + narration_buffer_ms)``; the difference is filled with a
pause, at the scene's ``hold: auto`` if it has one, else after its actions. Hidden
scenes are not recorded and take no time. The end card, when enabled, follows the
tail. Clip *n* is placed at its scene's start, so a timing error in one scene never
shifts the narration of the next.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from narratty.spec.model import Action, Enter, Hold, Key, Scene, Spec, TypeCommand


def typing_speed(spec: Spec, scene: Scene) -> int:
    """Milliseconds per typed key in ``scene``."""
    return scene.typing_speed_ms or spec.terminal.typing_speed_ms


def action_ms(action: Action, speed: int) -> int:
    """Deterministic duration of one action (``wait`` and ``hold: auto`` count as 0)."""
    if isinstance(action, TypeCommand):
        return len(action.type_command) * speed
    if isinstance(action, Enter):
        return speed
    if isinstance(action, Key):
        _, _, count = action.key.partition(" ")
        return speed * int(count or 1)
    if isinstance(action, Hold) and action.hold != "auto":
        return int(action.hold)
    return 0


@dataclass(frozen=True)
class SceneTiming:
    """Where one scene sits in the video."""

    scene_id: str
    hidden: bool
    start_ms: int
    action_ms: int
    audio_ms: int
    fill_ms: int
    audio_offset_ms: int

    @property
    def length_ms(self) -> int:
        """Recorded length of the scene (0 when hidden)."""
        return 0 if self.hidden else self.action_ms + self.fill_ms

    @property
    def audio_start_ms(self) -> int:
        """When this scene's narration starts in the video."""
        return self.start_ms + self.audio_offset_ms


@dataclass(frozen=True)
class Timeline:
    """Scene timings plus the lead-in, tail and end card around them."""

    scenes: tuple[SceneTiming, ...]
    lead_in_ms: int
    tail_ms: int
    end_card_ms: int = 0

    @property
    def total_ms(self) -> int:
        """Expected length of the video."""
        return self.lead_in_ms + sum(s.length_ms for s in self.scenes) + self.tail_ms + self.end_card_ms

    def scene(self, scene_id: str) -> SceneTiming:
        """Timing of the scene called ``scene_id``."""
        return next(s for s in self.scenes if s.scene_id == scene_id)


def build_timeline(spec: Spec, audio_ms: Mapping[str, int]) -> Timeline:
    """Compute the timeline from the spec and each narrated scene's clip length."""
    buffer = spec.timing.narration_buffer_ms
    cursor = spec.timing.lead_in_ms
    timings: list[SceneTiming] = []
    for scene in spec.scenes:
        speed = typing_speed(spec, scene)
        actions = sum(action_ms(action, speed) for action in scene.actions)
        audio = audio_ms.get(scene.id, 0) if scene.narration else 0
        if scene.hidden:
            timings.append(SceneTiming(scene.id, True, cursor, actions, 0, 0, 0))
            continue
        if scene.narration_start == "after_actions":
            offset, fill = actions, audio + buffer if audio else 0
        else:
            offset, fill = 0, max(0, audio + buffer - actions) if audio else 0
        timing = SceneTiming(scene.id, False, cursor, actions, audio, fill, offset)
        timings.append(timing)
        cursor += timing.length_ms
    end_card = spec.end_card.duration_ms if spec.end_card.enabled else 0
    return Timeline(tuple(timings), spec.timing.lead_in_ms, spec.timing.tail_ms, end_card)
