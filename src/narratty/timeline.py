"""The timeline: when each scene starts and how long it lasts in the video.

Narration starts when its scene starts (or after the scene's actions with
``narration_start: after_actions``). A scene lasts
``max(action_ms, audio_ms + narration_buffer_ms)``; the difference is filled with a
pause after its actions. A ``hold: auto`` waits until the narration and its buffer are
done, so the actions after it follow the narration (explain, then run). Hidden
scenes are not recorded and take no time. The end card, when enabled, follows the
tail. Clip *n* is placed at its scene's start, so a timing error in one scene never
shifts the narration of the next.

A timelapse scene is recorded in real time and sped up afterwards, so its length is
only known after recording (see :func:`timelapse_layout`); the plan counts its
deterministic actions, sped up.

``measured`` command durations (recorded by ``narratty check``, see
``narratty.durations``) lengthen the pause after a ``run`` whose command takes longer
than ``timing.run_hold_ms``, so the output is there before the scene goes on.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from narratty.spec.model import Action, CtrlSequence, Enter, Hold, Key, Run, Scene, Spec, TypeCommand


@dataclass(frozen=True)
class Pacing:
    """How fast one scene types and how long it pauses after keys and commands."""

    speed: int
    run_hold_ms: int = 0
    pause_ms: int = 0


def pacing(spec: Spec, scene: Scene) -> Pacing:
    """The pacing of ``scene``: its own values where set, else the spec's."""
    return Pacing(
        speed=scene.typing_speed_ms or spec.terminal.typing_speed_ms,
        run_hold_ms=spec.timing.run_hold_ms,
        pause_ms=spec.timing.pause_ms if scene.pause_ms is None else scene.pause_ms,
    )


def action_ms(action: Action, pace: Pacing) -> int:
    """Deterministic duration of one action (``wait`` and ``hold: auto`` count as 0)."""
    if isinstance(action, Run):
        typed = action.run if action.show is None else action.show  # the rest is typed hidden
        return (len(typed) + 1) * pace.speed + pace.run_hold_ms
    if isinstance(action, TypeCommand):
        return len(action.type_command) * pace.speed
    if isinstance(action, Enter):
        return pace.speed + pace.pause_ms
    if isinstance(action, Key):
        _, _, count = action.key.partition(" ")
        return pace.speed * int(count or 1) + pace.pause_ms
    if isinstance(action, CtrlSequence):
        return pace.pause_ms
    if isinstance(action, Hold) and action.hold != "auto":
        return int(action.hold)
    return 0


# Kept after a measured command's end, so its last output is on screen before going on.
MEASURED_SETTLE_MS = 300


def run_holds(
    spec: Spec, scene: Scene, measured: Mapping[tuple[str, int], int]
) -> tuple[tuple[int, int], ...]:
    """``(action index, pause)`` for each ``run`` whose measured command outlasts its pause."""
    base = spec.timing.run_hold_ms
    holds = []
    for index, action in enumerate(scene.actions):
        took = measured.get((scene.id, index))
        if isinstance(action, Run) and took is not None and took > base:
            holds.append((index, took + MEASURED_SETTLE_MS))
    return tuple(holds)


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
    timelapse: float | None = None
    hold_ms: int = 0  # timelapse only: narration plus buffer, waited for after the speed-up
    narration_after: bool = False
    run_holds: tuple[tuple[int, int], ...] = ()  # (action index, pause) from measured commands

    def run_hold(self, index: int, default: int) -> int:
        """Pause after the ``run`` at ``actions[index]``: measured, else ``default``."""
        return dict(self.run_holds).get(index, default)

    @property
    def length_ms(self) -> int:
        """Recorded length of the scene (0 when hidden)."""
        if self.timelapse:  # planned: waits count as 0
            sped = round(self.action_ms / self.timelapse)
            return sped + self.timelapse_layout(sped)[1]
        return 0 if self.hidden else self.action_ms + self.fill_ms

    def timelapse_layout(self, sped_ms: int) -> tuple[int, int]:
        """See :func:`timelapse_layout`."""
        return timelapse_layout(sped_ms, self.hold_ms, narration_after=self.narration_after)

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

    @property
    def has_timelapse(self) -> bool:
        """True when a scene is sped up after recording."""
        return any(s.timelapse for s in self.scenes)


def timelapse_layout(sped_ms: int, hold_ms: int, *, narration_after: bool) -> tuple[int, int]:
    """Where a timelapse scene's narration starts and how long its last frame is held.

    ``sped_ms`` is the scene's footage after the speed-up. Narration starts with the
    footage (or after it with ``after_actions``); the last frame stays until the
    narration and its buffer (``hold_ms``) are done. Returns ``(offset, freeze)``.
    """
    if narration_after:
        return sped_ms, hold_ms
    return 0, max(0, hold_ms - sped_ms)


def _before_auto_hold(scene: Scene, pace: Pacing, holds: tuple[tuple[int, int], ...], total: int) -> int:
    """How long the actions before the scene's ``hold: auto`` take; ``total`` without one."""
    index = next(
        (i for i, action in enumerate(scene.actions) if isinstance(action, Hold) and action.hold == "auto"),
        None,
    )
    if index is None:
        return total
    before = sum(action_ms(action, pace) for action in scene.actions[:index])
    return before + sum(hold - pace.run_hold_ms for at, hold in holds if at < index)


def build_timeline(
    spec: Spec, audio_ms: Mapping[str, int], measured: Mapping[tuple[str, int], int] | None = None
) -> Timeline:
    """Compute the timeline from the spec and each narrated scene's clip length.

    ``measured`` maps ``(scene id, action index)`` of a ``run`` to how long its command
    took (see ``narratty.durations``).
    """
    buffer = spec.timing.narration_buffer_ms
    cursor = spec.timing.lead_in_ms
    timings: list[SceneTiming] = []
    for scene in spec.scenes:
        pace = pacing(spec, scene)
        holds = run_holds(spec, scene, measured or {})
        actions = sum(action_ms(action, pace) for action in scene.actions)
        actions += sum(hold - pace.run_hold_ms for _, hold in holds)
        audio = audio_ms.get(scene.id, 0) if scene.narration else 0
        if scene.hidden:
            timings.append(SceneTiming(scene.id, True, cursor, actions, 0, 0, 0, run_holds=holds))
            continue
        if scene.timelapse:
            hold = audio + buffer if audio else 0
            after = scene.narration_start == "after_actions"
            timing = SceneTiming(
                scene.id,
                False,
                cursor,
                actions,
                audio,
                0,
                0,
                scene.timelapse,
                hold,
                narration_after=after,
                run_holds=holds,
            )
            timings.append(timing)
            cursor += timing.length_ms
            continue
        if scene.narration_start == "after_actions":
            offset, fill = actions, audio + buffer if audio else 0
        else:
            # Up to ``hold: auto`` if there is one: the actions after it wait for the narration.
            before = _before_auto_hold(scene, pace, holds, actions)
            offset, fill = 0, max(0, audio + buffer - before) if audio else 0
        timing = SceneTiming(scene.id, False, cursor, actions, audio, fill, offset, run_holds=holds)
        timings.append(timing)
        cursor += timing.length_ms
    end_card = spec.end_card.duration_ms if spec.end_card.enabled else 0
    return Timeline(tuple(timings), spec.timing.lead_in_ms, spec.timing.tail_ms, end_card)
