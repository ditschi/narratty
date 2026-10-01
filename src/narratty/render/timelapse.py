"""Timelapse scenes: find them in the VHS recording and speed them up with ffmpeg.

The same markers also place overlays where their cue was actually recorded.

VHS records in real time and has no markers of its own. The tape takes a
``Screenshot`` at each visible scene start and each timelapse end, and VHS prints
every command as it starts it, so the time a screenshot line appears is when that
point was recorded. Only shown time is recorded (``Hide`` stops the clock), and a
linear scale absorbs VHS's frame-rate drift.

Each timelapse scene is then sped up with ``setpts`` and its last frame is held
until the narration is done; scene starts are mapped into the final video, so each
clip is placed where its scene actually starts.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from narratty.errors import RenderError
from narratty.render.media import LogLine, Runner, _run, _tail, require
from narratty.render.tape import FRAMERATE
from narratty.timeline import Timeline

_SETUP = ("File:", "Output ", "Set ")


def _recorded(log: Sequence[LogLine]) -> Iterator[tuple[float, str]]:
    """Each command VHS ran, with the recorded (shown) seconds before it."""
    recorded, since = 0.0, None
    commands = itertools.dropwhile(lambda line: not _is_command(line.text.strip()), log)
    for index, line in enumerate(commands):
        if index == 0:
            since = line.at
        now = recorded + (line.at - since if since is not None else 0.0)
        text = line.text.strip()
        yield now, text
        if text == "Hide" and since is not None:
            recorded, since = now, None
        elif text == "Show" and since is None:
            since = line.at


def _is_command(text: str) -> bool:
    # Skips the file name, output, settings and browser download lines VHS prints first.
    return bool(text) and not text.startswith((*_SETUP, "[")) and text[:1].isupper()


def marker_positions(log: Sequence[LogLine], marks: Path, video_ms: int) -> dict[str, int]:
    """Position in the video (ms) of every marker in ``marks`` that VHS logged."""
    seconds: dict[str, float] = {}
    total = 0.0
    for now, text in _recorded(log):
        total = now
        if text.startswith("Creating "):
            break
        if text.startswith("Screenshot "):
            path = Path(text.removeprefix("Screenshot ").strip())
            if path.parent == marks:
                seconds[path.stem] = now
    if not seconds:
        raise RenderError("VHS logged no scene markers, so timelapse scenes cannot be located")
    scale = video_ms / (total * 1000) if total else 1.0
    return {label: round(value * 1000 * scale) for label, value in seconds.items()}


@dataclass(frozen=True)
class Segment:
    """A stretch of the recording shown ``factor`` times faster, then frozen ``freeze_ms``."""

    start_ms: int
    end_ms: int
    factor: float
    freeze_ms: int

    @property
    def sped_ms(self) -> int:
        """Length of the sped-up footage."""
        return round((self.end_ms - self.start_ms) / self.factor)

    @property
    def output_ms(self) -> int:
        """Length in the final video."""
        return self.sped_ms + self.freeze_ms


@dataclass(frozen=True)
class Layout:
    """Where everything lands in the final video."""

    segments: tuple[Segment, ...]
    scene_starts_ms: dict[str, int]
    narration_offsets_ms: dict[str, int]
    cues_ms: dict[str, int] = field(default_factory=dict)  # overlay starts, the end cue

    def expected_ms(self, timeline: Timeline) -> int:
        """The planned length, with each timelapse scene's measured length."""
        planned = sum(s.length_ms for s in timeline.scenes if s.timelapse)
        return timeline.total_ms - planned + sum(s.output_ms for s in self.segments)


def remap(position_ms: int, segments: Sequence[Segment]) -> int:
    """Where ``position_ms`` of the recording lands in the final video."""
    out, previous = 0, 0
    for segment in segments:
        if position_ms <= segment.start_ms:
            break
        out += segment.start_ms - previous
        if position_ms < segment.end_ms:
            return out + round((position_ms - segment.start_ms) / segment.factor)
        out += segment.output_ms
        previous = segment.end_ms
    return out + position_ms - previous


def layout(timeline: Timeline, positions: dict[str, int]) -> Layout:
    """Segments and final scene starts from the markers' positions in the recording."""
    segments: list[Segment] = []
    offsets: dict[str, int] = {}
    for timing in timeline.scenes:
        if timing.hidden:
            continue
        if not timing.timelapse:
            offsets[timing.scene_id] = timing.audio_offset_ms
            continue
        start = _position(positions, f"scene-{timing.scene_id}")
        end = max(start, _position(positions, f"end-{timing.scene_id}"))
        sped = round((end - start) / timing.timelapse)
        offset, freeze = timing.timelapse_layout(sped)
        segments.append(Segment(start, end, timing.timelapse, freeze))
        offsets[timing.scene_id] = offset
    starts = {
        timing.scene_id: remap(_position(positions, f"scene-{timing.scene_id}"), segments)
        for timing in timeline.scenes
        if not timing.hidden
    }
    cues = {
        label.removeprefix("cue-"): remap(position, segments)
        for label, position in positions.items()
        if label.startswith("cue-")
    }
    return Layout(tuple(segments), starts, offsets, cues)


def _position(positions: dict[str, int], label: str) -> int:
    if label not in positions:
        raise RenderError(f"VHS did not log the marker {label!r}")
    return positions[label]


def filter_graph(segments: Sequence[Segment], framerate: int = FRAMERATE) -> str:
    """ffmpeg filter that speeds up ``segments`` and keeps the rest as is."""
    parts: list[str] = []
    previous = 0
    for segment in segments:
        if segment.start_ms > previous:
            parts.append(f"trim=start={previous / 1000}:end={segment.start_ms / 1000},setpts=PTS-STARTPTS")
        speed = f"trim=start={segment.start_ms / 1000}:end={segment.end_ms / 1000}"
        speed += f",setpts=(PTS-STARTPTS)/{segment.factor:g},fps={framerate}"
        if segment.freeze_ms:
            speed += f",tpad=stop_mode=clone:stop_duration={segment.freeze_ms / 1000}"
        parts.append(speed)
        previous = segment.end_ms
    parts.append(f"trim=start={previous / 1000},setpts=PTS-STARTPTS")
    labels = [f"[s{index}]" for index in range(len(parts))]
    graph = [f"[0:v]split={len(parts)}{''.join(labels)}"]
    graph += [
        f"{label}{part}[v{index}]" for index, (label, part) in enumerate(zip(labels, parts, strict=True))
    ]
    graph.append(
        "".join(f"[v{index}]" for index in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=0[out]"
    )
    return ";".join(graph)


def speed_up(
    video: Path, segments: Sequence[Segment], out: Path, *, framerate: int = FRAMERATE, runner: Runner = _run
) -> None:
    """Write ``video`` with ``segments`` sped up to ``out``."""
    argv = [
        require("ffmpeg"), "-y", "-v", "error", "-i", str(video),
        "-filter_complex", filter_graph(segments, framerate), "-map", "[out]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-r", str(framerate), str(out),
    ]  # fmt: skip
    result = runner(argv)
    if result.returncode != 0:
        raise RenderError(f"ffmpeg failed to speed up the timelapse scenes:\n{_tail(result)}")
