"""Where the narration goes in the recorded video: per scene, or linearly as a fallback.

The tape takes a marker at every visible scene start, at every cue and, for scenes
with ``narration_start: after_actions``, where their actions ended (see
``narratty.render.timelapse``). Each clip is placed relative to its own scene's
recorded marker, so a slow command or a long ``wait`` in one scene moves only that
scene's narration, and ``hold: auto`` or ``after_actions`` keep their meaning.
Subtitles follow the placed clips; overlays, browser views and slides are timed by
their own cue markers.

Without markers, the planned positions are stretched linearly to the video's length
(:func:`linear_starts`).

With per-scene placement the video's total length no longer says whether it is in
sync: a longer scene only adds silence. What breaks sync is narration running past
the end of its scene (:func:`overruns`), into the next scene's picture and voice.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from narratty.render.script import END_CUE, narration_cue
from narratty.timeline import Timeline

# A video this much shorter than the time VHS spent recording lost frames under load.
DROP_TOLERANCE = 0.03
# Narration may run this far into the next scene without being worth a warning.
OVERRUN_GRACE_MS = 100


def narration_starts(
    timeline: Timeline,
    scene_starts: Mapping[str, int],
    cues: Mapping[str, int] | None = None,
    offsets: Mapping[str, int] | None = None,
) -> dict[str, int]:
    """Where each visible scene's narration starts in the video, from recorded markers.

    A scene's narration starts at its recorded start plus its planned offset
    (``offsets`` overrides it, e.g. for timelapse scenes), or at its narration cue
    (``after_actions``) when that was recorded. Scenes without a recorded start are
    left out.
    """
    cues, offsets = cues or {}, offsets or {}
    starts: dict[str, int] = {}
    for timing in timeline.scenes:
        if timing.hidden or timing.scene_id not in scene_starts:
            continue
        cue = cues.get(narration_cue(timing.scene_id))
        if cue is not None and not timing.timelapse:
            starts[timing.scene_id] = cue
            continue
        offset = offsets.get(timing.scene_id, timing.audio_offset_ms)
        starts[timing.scene_id] = scene_starts[timing.scene_id] + offset
    return starts


def linear_starts(timeline: Timeline, video_ms: int) -> dict[str, int]:
    """Planned narration starts, stretched by the ratio of video to planned length."""
    scale = video_ms / timeline.total_ms if timeline.total_ms else 1.0
    return {
        timing.scene_id: round(timing.audio_start_ms * scale)
        for timing in timeline.scenes
        if not timing.hidden
    }


def scene_ends(timeline: Timeline, scene_starts: Mapping[str, int], end_ms: int) -> dict[str, int]:
    """Where each visible scene ends: the next visible scene's start, or ``end_ms``."""
    visible = [t.scene_id for t in timeline.scenes if not t.hidden and t.scene_id in scene_starts]
    following = [scene_starts[scene_id] for scene_id in visible[1:]] + [end_ms]
    return dict(zip(visible, following, strict=True))


@dataclass(frozen=True)
class Overrun:
    """A scene whose narration runs past the scene's end in the video."""

    scene_id: str
    overrun_ms: int  # how far the narration runs into what follows
    audio_ms: int
    planned_ms: int  # the scene's planned length
    recorded_ms: int  # its length in the video
    pushed_ms: int = 0  # how much later the clip started, because the one before ran over

    @property
    def cause(self) -> str:
        """Why it happened, in a few words."""
        if self.pushed_ms > OVERRUN_GRACE_MS:
            return f"started {self.pushed_ms / 1000:.2f}s late after the previous narration"
        shorter = self.planned_ms - self.recorded_ms
        if shorter > OVERRUN_GRACE_MS:
            return f"scene recorded {shorter / 1000:.2f}s shorter than planned"
        return "narration longer than the scene"

    def describe(self) -> str:
        """``scene (0.80s over: cause)``."""
        return f"{self.scene_id} ({self.overrun_ms / 1000:.2f}s over: {self.cause})"


def overruns(
    timeline: Timeline,
    scene_starts: Mapping[str, int],
    end_ms: int,
    placed: Mapping[str, int],
    wanted: Mapping[str, int],
) -> list[Overrun]:
    """Narrated scenes whose clip, at ``placed``, ends after the scene does.

    ``wanted`` is where each clip should have started; ``placed`` where the narration
    track put it (later when the clip before it ran over).
    """
    ends = scene_ends(timeline, scene_starts, end_ms)
    found = []
    for timing in timeline.scenes:
        scene_id = timing.scene_id
        if scene_id not in placed or scene_id not in ends or not timing.audio_ms:
            continue
        over = placed[scene_id] + timing.audio_ms - ends[scene_id]
        if over > OVERRUN_GRACE_MS:
            found.append(
                Overrun(
                    scene_id,
                    over,
                    timing.audio_ms,
                    timing.length_ms,
                    ends[scene_id] - scene_starts[scene_id],
                    max(0, placed[scene_id] - wanted.get(scene_id, placed[scene_id])),
                )
            )
    return found


def too_far(found: Sequence[Overrun], max_drift: float) -> list[Overrun]:
    """The overruns longer than ``max_drift`` of their narration."""
    return [item for item in found if item.overrun_ms > max_drift * item.audio_ms]


def end_of_scenes(cues: Mapping[str, int], video_ms: int) -> int:
    """Where the last scene ends: the end cue, else the end of the video."""
    return cues.get(END_CUE, video_ms)


def retime_factor(video_ms: int, recorded_ms: int, tolerance: float = DROP_TOLERANCE) -> float | None:
    """How much to stretch a video VHS made shorter than the time it recorded, or None.

    VHS captures frames in real time and writes them at a fixed frame rate; frames it
    could not capture (a busy machine) are missing, so the video runs fast. Stretching
    it by ``recorded_ms / video_ms`` puts every frame back at the time it was taken.
    """
    if video_ms <= 0 or recorded_ms <= 0 or video_ms >= recorded_ms * (1 - tolerance):
        return None
    return recorded_ms / video_ms
