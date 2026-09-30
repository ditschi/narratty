"""The whole pipeline: spec → narration clips → timeline → tape → silent video → mp4."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path

from narratty.cache import AudioCache
from narratty.diff import BASE_ENV as DIFF_BASE_ENV
from narratty.end_card import with_end_card
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
from narratty.workspace import PreparedWorkspace, export_artifacts, prepare_workspace

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
    def workspace_source(self) -> Path:
        """``workspace.source``, relative to the spec."""
        return self.source_of(self.spec_path, self.spec)

    @staticmethod
    def source_of(spec_path: Path, spec: Spec) -> Path:
        """``workspace.source`` of ``spec``, resolved relative to its file."""
        return (spec_path.resolve().parent / spec.workspace.source).resolve()


def plan(spec_path: Path, *, offline: bool = False, end_card: bool | None = None) -> Plan:
    """Load ``spec_path``, synthesize (or reuse) its narration and compute the timeline.

    ``end_card`` overrides the spec and the user's config (see ``narratty.end_card``).
    """
    spec = with_end_card(load_spec(spec_path), end_card)
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


@dataclass(frozen=True)
class WorkspaceOptions:
    """Command-line choices about the workspace."""

    mode: str | None = None
    allow_dirty: bool = False
    keep: bool = False


def workspace_for(
    planned: Plan, options: WorkspaceOptions, *, in_container: bool = False, log: Log | None = None
) -> AbstractContextManager[PreparedWorkspace]:
    """The prepared workspace (inside the container: the one the host mounted)."""
    if override := os.environ.get("NARRATTY_WORKSPACE"):
        path = Path(override)
        return nullcontext(PreparedWorkspace(path, "rw", path))
    spec = planned.spec
    return prepare_workspace(
        planned.workspace_source,
        options.mode or spec.workspace.mode,
        scratch=cache_dir() / "workspaces",
        include_uncommitted=spec.workspace.include_uncommitted,
        allow_dirty=options.allow_dirty,
        keep=options.keep,
        in_container=in_container,
        log=log,
    )


def warn_unenforced_sandbox(spec: Spec, log: Log) -> None:
    """Native runs cannot restrict network or mounts; say so once."""
    if spec.sandbox.elevated and not os.environ.get("NARRATTY_IN_CONTAINER"):
        log("sandbox settings are only enforced in a container; running natively with your own access")


def recording_env(spec: Spec, work: Path) -> dict[str, str]:
    """Environment the recorded shell gets on top of the usual one."""
    # The diff baseline lives in the work directory, so it is removed with it.
    return {**spec.sandbox.env, DIFF_BASE_ENV: str(work / "diff-base")}


def render_silent(planned: Plan, video: Path, work: Path, workspace: Path) -> Path:
    """Write the tape into ``work`` and record it with VHS in ``workspace`` into ``video``."""
    tape = work / "scene.tape"
    tape.write_text(generate_tape(planned.spec, planned.timeline, video.resolve()), encoding="utf-8")
    media.run_vhs(tape, workspace, extra_env=recording_env(planned.spec, work))
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
    workspace: WorkspaceOptions | None = None,
    end_card: bool | None = None,
    log: Log | None = None,
) -> BuildResult:
    """Run the full pipeline and verify the result."""
    say = log or (lambda _message: None)
    output = (output or default_output(spec_path)).resolve()
    say("synthesizing narration")
    planned = plan(spec_path, offline=offline, end_card=end_card)
    warn_unenforced_sandbox(planned.spec, say)
    with (
        work_directory(work_dir) as work,
        workspace_for(planned, workspace or WorkspaceOptions(), log=say) as ws,
    ):
        say(f"recording {len(planned.timeline.scenes)} scenes with VHS")
        silent = render_silent(planned, work / "silent.mp4", work, ws.path)
        video_ms = media.probe(silent).duration_ms
        placements = place_clips(planned, video_ms)
        say("mixing narration")
        track = work / "narration.wav"
        used = build_track(placements, video_ms, track)
        media.mux(silent, track, output)
        _export_artifacts(planned, ws.path, output, say)
    result = BuildResult(output, planned.timeline.total_ms, video_ms, tuple(used))
    verify(result, max_drift=max_drift)
    return result


def _export_artifacts(planned: Plan, workspace: Path, output: Path, say: Log) -> None:
    if planned.spec.workspace.artifacts:
        dest = output.with_name(output.name.removesuffix(output.suffix) + ".artifacts")
        copied = export_artifacts(workspace, planned.spec.workspace.artifacts, dest)
        say(f"exported {len(copied)} artifacts to {dest}")


@dataclass(frozen=True)
class CastOutputs:
    """The files of a cast build: the page and, beside it, the cast and its audio."""

    page: Path

    @property
    def cast(self) -> Path:
        """The asciicast (v2)."""
        return self.page.with_suffix(".cast")

    @property
    def audio(self) -> Path:
        """The narration track (MP3)."""
        return self.page.with_suffix(".mp3")


def place_clips_at(planned: Plan, scene_starts_ms: dict[str, int]) -> list[Placement]:
    """Clip positions at the recorded start of each scene."""
    return [
        Placement(
            clip.scene_id,
            clip.path,
            scene_starts_ms[clip.scene_id] + planned.timeline.scene(clip.scene_id).audio_offset_ms,
        )
        for clip in planned.clips
    ]


def build_cast(
    spec_path: Path,
    output: Path | None = None,
    *,
    work_dir: Path | None = None,
    offline: bool = False,
    workspace: WorkspaceOptions | None = None,
    end_card: bool | None = None,
    log: Log | None = None,
) -> BuildResult:
    """Record an asciicast with a narration track and a page that plays both.

    ``output`` is the HTML page; the ``.cast`` and ``.mp3`` are written beside it.
    Clips are placed at the recorded start of their scene, so there is no drift to check.
    """
    from narratty.render.cast import record
    from narratty.render.player import player_page, player_theme
    from narratty.render.script import build_script

    say = log or (lambda _message: None)
    outputs = CastOutputs((output or default_output(spec_path, ".html")).resolve())
    say("synthesizing narration")
    planned = plan(spec_path, offline=offline, end_card=end_card)
    warn_unenforced_sandbox(planned.spec, say)
    spec = planned.spec
    with (
        work_directory(work_dir) as work,
        workspace_for(planned, workspace or WorkspaceOptions(), log=say) as ws,
    ):
        say(f"recording {len(planned.timeline.scenes)} scenes as an asciicast")
        recording = record(
            build_script(spec, planned.timeline),
            terminal=spec.terminal,
            cwd=ws.path,
            env={**os.environ, **recording_env(spec, work)},
            title=spec.meta.title,
        )
        outputs.page.parent.mkdir(parents=True, exist_ok=True)
        outputs.cast.write_text(recording.cast, encoding="utf-8")
        say("mixing narration")
        track = work / "narration.wav"
        used = build_track(place_clips_at(planned, recording.scene_starts_ms), recording.duration_ms, track)
        media.encode_mp3(track, outputs.audio)
        page = player_page(
            spec.meta.title, recording.cast, outputs.audio, theme=player_theme(spec.terminal.theme)
        )
        outputs.page.write_text(page, encoding="utf-8")
        _export_artifacts(planned, ws.path, outputs.page, say)
    return BuildResult(outputs.page, planned.timeline.total_ms, recording.duration_ms, tuple(used))


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
