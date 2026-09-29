"""The whole pipeline: spec → narration clips → timeline → tape → silent video → mp4."""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from narratty.cache import AudioCache
from narratty.errors import RenderError, SyncError
from narratty.paths import cache_dir, data_dir
from narratty.render import media
from narratty.render.narration import Placement, build_track
from narratty.render.tape import generate_tape
from narratty.spec import load_spec
from narratty.spec.model import Spec
from narratty.timeline import Timeline, build_timeline
from narratty.tts.registry import get_provider
from narratty.tts.synth import Clip, synthesize_spec

SPEC_SUFFIXES = (".narratty.yaml", ".narratty.yml", ".yaml", ".yml")
DEFAULT_MAX_DRIFT = 0.10

Log = Callable[[str], None]


def default_output(spec_path: Path, suffix: str = ".mp4") -> Path:
    """``demo.narratty.yaml`` → ``demo.mp4`` next to the spec."""
    name = spec_path.name
    for known in SPEC_SUFFIXES:
        if name.endswith(known):
            return spec_path.with_name(name.removesuffix(known) + suffix)
    return spec_path.with_suffix(suffix)


@dataclass(frozen=True)
class Plan:
    """A loaded spec with its narration synthesized and its timeline computed."""

    spec_path: Path
    spec: Spec
    clips: tuple[Clip, ...]
    timeline: Timeline

    @property
    def workspace(self) -> Path:
        """Directory the recorded shell starts in."""
        return (self.spec_path.parent / self.spec.workspace.source).resolve()


def plan(spec_path: Path, *, offline: bool = False) -> Plan:
    """Load ``spec_path``, synthesize (or reuse) its narration and compute the timeline."""
    spec = load_spec(spec_path)
    provider = get_provider(spec.tts.provider, data_dir())
    clips = synthesize_spec(spec, provider, AudioCache(cache_dir()), download=not offline)
    timeline = build_timeline(spec, {clip.scene_id: clip.duration_ms for clip in clips})
    return Plan(spec_path, spec, tuple(clips), timeline)


@contextmanager
def work_directory(path: Path | None) -> Iterator[Path]:
    """``path`` (created and kept) or a temporary directory removed afterwards."""
    if path is not None:
        path.mkdir(parents=True, exist_ok=True)
        yield path.resolve()
        return
    with tempfile.TemporaryDirectory(prefix="narratty-") as tmp:
        yield Path(tmp)


def render_silent(planned: Plan, video: Path, work: Path) -> Path:
    """Write the tape into ``work`` and record it with VHS into ``video``."""
    tape = work / "scene.tape"
    tape.write_text(generate_tape(planned.spec, planned.timeline, video.resolve()), encoding="utf-8")
    workspace = planned.workspace
    if not workspace.is_dir():
        raise RenderError(
            f"workspace {workspace} does not exist", hint="Check `workspace.source` in the spec."
        )
    media.run_vhs(tape, workspace)
    if not video.is_file():
        raise RenderError(f"VHS finished but wrote no video to {video}")
    return video


@dataclass(frozen=True)
class BuildResult:
    """What ``build`` produced and how well it matched the timeline."""

    output: Path
    expected_ms: int
    video_ms: int
    placements: tuple[Placement, ...]

    @property
    def drift(self) -> float:
        """Relative difference between the rendered and the planned length."""
        return (self.video_ms - self.expected_ms) / self.expected_ms if self.expected_ms else 0.0


def place_clips(planned: Plan, video_ms: int) -> list[Placement]:
    """Clip positions, stretched by the ratio of rendered to planned length.

    VHS runs slightly faster or slower than its nominal timing (a few percent,
    depending on the machine); scaling keeps each clip at its scene's actual start.
    """
    scale = video_ms / planned.timeline.total_ms if planned.timeline.total_ms else 1.0
    return [
        Placement(
            clip.scene_id, clip.path, round(planned.timeline.scene(clip.scene_id).audio_start_ms * scale)
        )
        for clip in planned.clips
    ]


def build(
    spec_path: Path,
    output: Path | None = None,
    *,
    work_dir: Path | None = None,
    offline: bool = False,
    max_drift: float = DEFAULT_MAX_DRIFT,
    log: Log | None = None,
) -> BuildResult:
    """Run the full pipeline and verify the result."""
    say = log or (lambda _message: None)
    output = (output or default_output(spec_path)).resolve()
    say("synthesizing narration")
    planned = plan(spec_path, offline=offline)
    with work_directory(work_dir) as work:
        say(f"recording {len(planned.timeline.scenes)} scenes with VHS")
        silent = render_silent(planned, work / "silent.mp4", work)
        video_ms = media.probe(silent).duration_ms
        placements = place_clips(planned, video_ms)
        say("mixing narration")
        track = work / "narration.wav"
        used = build_track(placements, video_ms, track)
        media.mux(silent, track, output)
    result = BuildResult(output, planned.timeline.total_ms, video_ms, tuple(used))
    verify(result, max_drift=max_drift)
    return result


def verify(result: BuildResult, *, max_drift: float) -> None:
    """Fail when the output lacks a stream or drifted beyond ``max_drift``."""
    info = media.probe(result.output)
    if not (info.has_video and info.has_audio):
        raise RenderError(f"{result.output} is missing its {'audio' if info.has_video else 'video'} stream")
    if abs(result.drift) > max_drift:
        raise SyncError(
            f"the video is {result.video_ms / 1000:.2f}s long but the timeline planned "
            f"{result.expected_ms / 1000:.2f}s ({result.drift:+.0%})",
            hint="A command or `wait` took longer than its scene; add a `hold` or move slow "
            "commands into a hidden scene.",
        )
