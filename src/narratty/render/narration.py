"""Build the narration track: every clip placed at its scene's start, silence between."""

from __future__ import annotations

import wave
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from narratty.errors import RenderError


@dataclass(frozen=True)
class Placement:
    """A clip and where it starts in the video."""

    scene_id: str
    path: Path
    start_ms: int


def build_track(placements: Sequence[Placement], total_ms: int, out: Path) -> list[Placement]:
    """Write one mono WAV of ``total_ms`` with each clip at its start.

    Clips that would overlap the previous one are pushed back; the returned list holds
    the positions actually used. All clips must share one sample rate and format.
    """
    params: tuple[int, int, int] | None = None
    frames: list[tuple[Placement, bytes]] = []
    for placement in placements:
        with wave.open(str(placement.path), "rb") as clip:
            clip_params = (clip.getnchannels(), clip.getsampwidth(), clip.getframerate())
            if params is None:
                params = clip_params
            elif clip_params != params:
                raise RenderError(f"clip for scene {placement.scene_id!r} has a different audio format")
            frames.append((placement, clip.readframes(clip.getnframes())))
    channels, width, rate = params or (1, 2, 22050)
    frame_size = channels * width

    def to_frames(ms: int) -> int:
        return ms * rate // 1000

    used: list[Placement] = []
    track = bytearray()
    for placement, data in sorted(frames, key=lambda item: item[0].start_ms):
        start = max(to_frames(placement.start_ms), len(track) // frame_size)
        track += bytes((start * frame_size) - len(track))
        track += data
        used.append(Placement(placement.scene_id, placement.path, start * 1000 // rate))
    end = max(to_frames(total_ms), len(track) // frame_size)
    track += bytes(end * frame_size - len(track))
    with wave.open(str(out), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(bytes(track))
    return used
