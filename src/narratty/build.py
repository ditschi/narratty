"""The whole pipeline: spec → narration clips → timeline → tape → silent video → mp4."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from narratty.cache import AudioCache
from narratty.end_card import with_end_card
from narratty.errors import RenderError, SyncError
from narratty.paths import cache_dir, data_dir
from narratty.render import media, timelapse
from narratty.render.narration import Placement, build_track
from narratty.render.subtitles import Narrated, SubtitleFiles, cues_for, to_srt
from narratty.spec import load_spec
from narratty.spec.model import Run, ShowBrowser, ShowOverlay, ShowSlide, Spec
from narratty.sync import Overrun, end_of_scenes, linear_starts, narration_starts, overruns, too_far
from narratty.timeline import Timeline, build_timeline
from narratty.tts.lexicon import load_lexicon
from narratty.tts.registry import get_provider
from narratty.tts.synth import Clip, synthesize_spec
from narratty.workspace import PreparedWorkspace, export_artifacts, prepare_workspace

if TYPE_CHECKING:
    from narratty.container import SandboxRequest
    from narratty.render.cast import Recording
    from narratty.render.overlays import OverlayImage
    from narratty.render.pauses import Insert, JobWatch
    from narratty.render.scene_cache import SceneCache, SceneRecording
    from narratty.render.script import HelperPlacement
    from narratty.render.tape import Tape
    from narratty.spec.model import Environment

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
    draft: bool = False

    @property
    def workspace_source(self) -> Path:
        """``workspace.source``, relative to the spec."""
        return self.source_of(self.spec_path, self.spec)

    @staticmethod
    def source_of(spec_path: Path, spec: Spec) -> Path:
        """``workspace.source`` of ``spec``, resolved relative to its file."""
        return (spec_path.resolve().parent / spec.workspace.source).resolve()


def plan(
    spec_path: Path,
    *,
    offline: bool = False,
    end_card: bool | None = None,
    draft: bool = False,
    log: Log | None = None,
) -> Plan:
    """Load ``spec_path``, synthesize (or reuse) its narration and compute the timeline.

    ``end_card`` overrides the spec and the user's config (see ``narratty.end_card``).
    A ``draft`` skips TTS: it has no clips and estimated narration lengths (see
    ``narratty.draft``). Commands wait as long as ``narratty check`` measured them (see
    ``narratty.durations``).
    """
    from narratty import durations

    spec = with_end_card(load_spec(spec_path), end_card)
    measured = durations.load(spec, cache_dir(), log)
    if draft:
        from narratty.draft import estimated_audio_ms

        return Plan(spec_path, spec, (), build_timeline(spec, estimated_audio_ms(spec), measured), draft=True)
    provider = get_provider(spec.tts.provider, data_dir())
    lexicon = load_lexicon(spec_path, spec.tts)
    clips = synthesize_spec(
        spec, provider, AudioCache(cache_dir()), download=not offline, lexicon=lexicon, log=log
    )
    timeline = build_timeline(spec, {clip.scene_id: clip.duration_ms for clip in clips}, measured)
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
    planned: Plan,
    options: WorkspaceOptions,
    sandbox: SandboxRequest | None = None,
    *,
    log: Log | None = None,
) -> AbstractContextManager[PreparedWorkspace]:
    """The prepared workspace (inside the container: the one the host mounted)."""
    if override := os.environ.get("NARRATTY_WORKSPACE"):
        path = Path(override)
        return nullcontext(PreparedWorkspace(path, "rw", path))
    spec = planned.spec
    in_container = _environment(spec, sandbox) is not None  # ro is enforced there
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


def warn_unenforced_sandbox(spec: Spec, log: Log, request: SandboxRequest | None = None) -> None:
    """Native runs cannot restrict network or mounts; say so once."""
    if _environment(spec, request) is not None:
        return  # the environment's container enforces them
    if spec.sandbox.elevated and not os.environ.get("NARRATTY_IN_CONTAINER"):
        log("sandbox settings are only enforced in a container; running natively with your own access")


def recording_env(spec: Spec) -> dict[str, str]:
    """Environment the recorded shell gets on top of the usual one."""
    return dict(spec.sandbox.env)


def placement_for(
    planned: Plan, work: Path, bridge: Sequence[str] | None, request: SandboxRequest | None = None
) -> HelperPlacement:
    """Where the demo's shell and narratty's helpers (editor layout, diff) run.

    Without a project environment, here. With one, the shell runs there, and so does
    anything typed into it. The editor layout is the exception when narratty shares the
    workspace with the environment (image, compose): tmux and yazi stay here, and only
    the layout's terminal pane opens the shell there. The diff baseline then lives in
    the work directory, which is removed with it; in the environment it is a temp dir.
    """
    from narratty.render.script import HelperPlacement
    from narratty.render.shell_hooks import SHELL_ARGV

    spec = planned.spec
    if bridge is None:
        return HelperPlacement(diff_base=str(work / "diff-base"))
    environment = _environment(spec, request)
    where = "in the project environment"
    if spec.terminal.layout == "editor" and environment is not None and environment.source != "container":
        terminal = shlex.join([*bridge, *SHELL_ARGV[spec.terminal.shell]])
        return HelperPlacement(diff_base=str(work / "diff-base"), terminal=terminal, where="on this machine")
    return HelperPlacement(diff_base=f"/tmp/narratty-diff-{uuid.uuid4().hex[:12]}", bridged=True, where=where)  # noqa: S108


def _environment(spec: Spec, request: SandboxRequest | None) -> Environment | None:
    from narratty import bridge
    from narratty.environment import EnvironmentOptions, resolve
    from narratty.runtime import IN_CONTAINER_ENV

    if os.environ.get(IN_CONTAINER_ENV) and bridge.current() is None:
        return None  # the host chose to run the demo in the narratty container
    return resolve(spec.environment, request.environment if request else EnvironmentOptions())


@contextmanager
def environment_bridge(
    planned: Plan, workspace: PreparedWorkspace, request: SandboxRequest | None, log: Log | None = None
) -> Iterator[list[str] | None]:
    """The bridge to the demo shell's environment, or None to run the shell locally.

    In the narratty container the host passes the bridge in; natively this starts the
    environment and bridges with ``docker exec``.
    """
    from narratty import bridge

    if (given := bridge.current()) is not None:
        yield given
        return
    environment = _environment(planned.spec, request)
    if environment is None:
        yield None
        return
    from narratty.container import SandboxRequest, approved_sandbox, image_ref
    from narratty.env_provide import provide
    from narratty.environment import running
    from narratty.runtime import container_engine

    engine = container_engine()
    if (kept := running(engine, planned.spec_path)) is not None:
        if log:
            log(f"using the environment {kept[0].container} from `narratty env up`")
        yield kept[0].exec_bridge()
        return
    request = request or SandboxRequest()
    sandbox = approved_sandbox(planned.spec_path, planned.spec, request)
    with provide(
        environment,
        planned.spec,
        spec_dir=planned.spec_path.resolve().parent,
        sandbox=sandbox,
        workspace=workspace,
        engine=engine,
        narratty_image=image_ref(),
        with_agent=False,
        keep=request.environment.keep,
        rebuild=request.environment.rebuild,
        log=log,
    ) as session:
        yield session.exec_bridge()


REMOTE_EXIT_LOG_ENV = "NARRATTY_REMOTE_EXIT_LOG"


def fresh_exit_log(work: Path, bridge: Sequence[str] | None = None) -> Path:
    """Where the recorded shell logs its commands' exit codes.

    Locally an empty ``exits.log`` in ``work``. With a ``bridge`` the shell runs in the
    project environment, so the log is a file there; :func:`collect_exit_log` (or the
    host, see ``NARRATTY_REMOTE_EXIT_LOG``) copies it into ``work`` afterwards.
    """
    log = work / "exits.log"
    if bridge is not None:
        log.unlink(missing_ok=True)
        return Path(os.environ.get(REMOTE_EXIT_LOG_ENV) or remote_exit_log())
    log.write_text("", encoding="utf-8")
    return log


def remote_exit_log() -> str:
    """A fresh path for the exit log in a project environment."""
    return f"/tmp/narratty-exits-{uuid.uuid4().hex[:12]}.log"  # noqa: S108 - inside the environment


def read_remote_exit_log(exec_argv: Sequence[str], remote: str) -> str | None:
    """The log at ``remote`` in the environment, read (and removed) with ``exec_argv``.

    ``exec_argv`` is a ``docker exec`` bridge; its terminal flags are dropped. None when
    it cannot be read (an image without ``sh``).
    """
    argv = [arg for arg in exec_argv if arg not in ("--interactive", "--tty")]
    quoted = shlex.quote(remote)
    try:
        result = subprocess.run(  # noqa: S603
            [*argv, "sh", "-c", f"cat {quoted} 2>/dev/null; rm -f {quoted}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    return result.stdout if result.returncode == 0 else None


def collect_exit_log(bridge: Sequence[str] | None, remote: Path, work: Path) -> None:
    """Copy the environment's exit log into ``work`` (``docker exec`` bridges only).

    In the narratty container the bridge is the agent, which cannot read files; the
    host collects the log there once the recording is done.
    """
    if bridge is None or len(bridge) < 2 or bridge[1] != "exec":
        return
    text = read_remote_exit_log(bridge, str(remote))
    if text is not None:
        (work / "exits.log").write_text(text, encoding="utf-8")


def check_exits(planned: Plan, work: Path, output: Path | None, *, ignore_exit: bool = False) -> None:
    """Fail when a command's exit code contradicts its ``expect_exit``.

    ``ignore_exit`` makes ``any`` the default; a scene's or action's own setting wins.
    """
    from narratty.render.exits import check

    check(planned.spec, work / "exits.log", default="any" if ignore_exit else "success", output=output)


def render_silent(
    planned: Plan,
    video: Path,
    work: Path,
    workspace: Path,
    bridge: Sequence[str] | None = None,
    *,
    fast: bool = False,
    log: Log | None = None,
    request: SandboxRequest | None = None,
    cache_markers: bool = False,
    cached_prefix: SceneRecording | None = None,
    replay_scenes: frozenset[str] = frozenset(),
    fresh: FreshFootage | None = None,
    align: bool = True,
) -> timelapse.Layout | None:
    """Write the tape into ``work`` and record it with VHS in ``workspace`` into ``video``.

    With a ``bridge`` the shell runs in the project environment.

    ``fast`` records long pauses briefly and fills them with still frames (see
    ``narratty.render.pauses``), except in scenes with ``fast: false``; scenes with
    ``fast: true`` do so without it. A pause whose screen was not still fails the build,
    except in a draft, which only logs it.

    With ``align`` (or timelapse scenes, overlays, browser views, the scene cache) the
    tape takes markers, so the returned layout says where each scene and cue landed
    (see ``narratty.sync``); timelapse scenes are sped up into ``video``, and a
    recording that lost frames is stretched back to the time it took. Without markers,
    or when VHS logged none that were only wanted for ``align``, the result is None.

    ``cached_prefix`` footage is joined before the recording of the scenes after
    ``replay_scenes``; ``fresh`` then learns where that recording is and its markers.
    """
    from narratty.draft import FRAMERATE as DRAFT_FRAMERATE
    from narratty.render.tape import FRAMERATE, build_tape, uses_fast

    tape_path = work / "scene.tape"
    filling = uses_fast(planned.spec, fast)
    framerate = DRAFT_FRAMERATE if planned.draft else FRAMERATE
    needs_marks = cache_markers or _needs_markers(planned)
    marks = (work / "marks").resolve() if needs_marks or align else None
    recording = work / "recording.mp4" if marks or filling else video
    if marks:
        marks.mkdir(parents=True, exist_ok=True)
    timeline = planned.timeline
    if cached_prefix is not None:
        from dataclasses import replace

        timeline = replace(timeline, lead_in_ms=0)
    tape = build_tape(
        planned.spec,
        timeline,
        recording.resolve(),
        framerate=framerate,
        marks=marks,
        exit_log=(exit_log := fresh_exit_log(work, bridge)),
        placement=(placement := placement_for(planned, work, bridge, request)),
        fast=fast,
        replay_scenes=replay_scenes,
    )
    tape_path.write_text(tape.text, encoding="utf-8")
    vhs_log, jobs = _run_tape(planned, tape, tape_path, workspace, work, bridge, placement, filling=filling)
    collect_exit_log(bridge, exit_log, work)
    if not recording.is_file():
        raise RenderError(f"VHS finished but wrote no video to {recording}")
    if jobs is None and marks is None:
        return None
    recording = _restore_dropped_frames(recording, vhs_log, work, framerate, log) if marks else recording
    recorded = media.probe(recording)
    inserts: list[Insert] = []
    if jobs is not None:
        filled = work / "filled.mp4" if marks else video
        inserts = _fill_pauses(
            planned, tape, vhs_log, jobs, recording, filled, log or (lambda _message: None)
        )
        recording = filled
    if marks is None:
        return None
    from narratty.render.pauses import shift_positions

    found = _marker_positions(vhs_log, marks, recorded.duration_ms, required=needs_marks, log=log)
    if found is None:
        recording.replace(video)
        return None
    positions = shift_positions(found, inserts, recorded.frame_rate)
    if fresh is not None:
        fresh.video, fresh.positions = recording, dict(positions)
    return _finish_recording(
        planned, recording, video, positions, cached_prefix, replay_scenes, framerate, recorded.frame_rate
    )


def _run_tape(
    planned: Plan,
    tape: Tape,
    tape_path: Path,
    workspace: Path,
    work: Path,
    bridge: Sequence[str] | None,
    placement: HelperPlacement,
    *,
    filling: bool,
) -> tuple[list[media.LogLine], JobWatch | None]:
    """Record ``tape_path`` with VHS; with ``filling``, watch the commands during its pauses."""
    from narratty.bridge import shim_env

    jobs = None
    if filling:
        from narratty.render.pauses import JobWatch

        jobs = JobWatch(tape.pauses)
    extra_env = recording_env(planned.spec)
    if placement.bridged:
        extra_env["PATH"] = shim_env(work / "shims", bridge or [], os.environ)["PATH"]
    vhs_log = media.run_vhs(
        tape_path, workspace, extra_env=extra_env, on_line=_progress_watch(jobs) if jobs else None
    )
    return vhs_log, jobs


def _needs_markers(planned: Plan) -> bool:
    """Whether the recording cannot be used without markers (timelapse, overlays, views)."""
    return planned.timeline.has_timelapse or has_overlays(planned.spec) or has_browsers(planned.spec)


def _marker_positions(
    vhs_log: list[media.LogLine], marks: Path, video_ms: int, *, required: bool, log: Log | None
) -> dict[str, int] | None:
    """The markers' positions; None when VHS logged none and they were only wanted for sync."""
    try:
        return timelapse.marker_positions(vhs_log, marks, video_ms)
    except RenderError:
        if required:
            raise
    if log:
        log("VHS logged no scene markers; placing narration by the planned timing")
    return None


def _restore_dropped_frames(
    recording: Path, vhs_log: list[media.LogLine], work: Path, framerate: int, log: Log | None
) -> Path:
    """``recording``, stretched to the time VHS spent on it if it lost frames (see narratty.sync)."""
    from narratty.sync import retime_factor

    took_ms, video_ms = timelapse.recorded_ms(vhs_log), media.probe(recording).duration_ms
    factor = retime_factor(video_ms, took_ms)
    if factor is None:
        return recording
    if log:
        log(
            f"warning: VHS recorded {took_ms / 1000:.2f}s into a {video_ms / 1000:.2f}s video "
            f"({video_ms / took_ms - 1:+.0%}); it dropped frames, the machine was probably busy. "
            "Stretching the recording back to real time"
        )
    retimed = work / "retimed.mp4"
    timelapse.retime(recording, factor, retimed, framerate=framerate)
    return retimed


def _finish_recording(
    planned: Plan,
    recording: Path,
    video: Path,
    positions: dict[str, int],
    cached_prefix: SceneRecording | None,
    replay_scenes: frozenset[str],
    framerate: int,
    recorded_framerate: float,
) -> timelapse.Layout:
    if cached_prefix is not None:
        if recorded_framerate <= 0:
            raise RenderError("cannot join cached scenes without a known video frame rate")
        parts: list[tuple[Path, int, int | None]] = []
        prefix_output_frames = 0
        for part in cached_prefix.parts:
            part_framerate = media.probe(part.video).frame_rate
            if part_framerate <= 0:
                raise RenderError("cannot join cached scenes without a known video frame rate")
            start = round(part.start_ms * part_framerate / 1000)
            end = round(part.end_ms * part_framerate / 1000)
            parts.append((part.video, start, end))
            prefix_output_frames += round((end - start) * framerate / part_framerate)
        first = next(
            scene.id for scene in planned.spec.scenes if not scene.hidden and scene.id not in replay_scenes
        )
        suffix_frame = round(positions[f"scene-{first}"] * recorded_framerate / 1000)
        media.join_recordings([*parts, (recording, suffix_frame, None)], video, framerate=framerate)
        positions = {
            key: _joined_position(value, prefix_output_frames, suffix_frame, recorded_framerate, framerate)
            for key, value in positions.items()
        } | {f"scene-{scene_id}": cached_prefix.starts_ms[scene_id] for scene_id in replay_scenes}
        return timelapse.layout(planned.timeline, positions)
    layout = timelapse.layout(planned.timeline, positions)
    if layout.segments:
        timelapse.speed_up(recording, layout.segments, video, framerate=framerate)
    else:
        recording.replace(video)
    return layout


def _joined_position(
    position_ms: int, prefix_frames: int, suffix_frame: int, suffix_rate: float, output_rate: int
) -> int:
    """Position a suffix marker after the cached prefix in the joined video."""
    suffix_frames = round(position_ms * suffix_rate / 1000) - suffix_frame
    output_frames = prefix_frames + suffix_frames * output_rate / suffix_rate
    return round(output_frames * 1000 / output_rate)


def _progress_watch(jobs: JobWatch) -> Callable[[media.LogLine, int], None]:
    """``on_line`` for :func:`media.run_vhs`: tells ``jobs`` about each progress line."""
    count = 0

    def on_line(line: media.LogLine, vhs_pid: int) -> None:
        nonlocal count
        if media.is_progress(line):
            jobs(count, vhs_pid)
            count += 1

    return on_line


def _fill_pauses(
    planned: Plan,
    tape: Tape,
    vhs_log: list[media.LogLine],
    jobs: JobWatch,
    recorded: Path,
    video: Path,
    say: Log,
) -> list[Insert]:
    """Write recorded with its shortened pauses filled to video; returns the inserts."""
    from narratty.render.pauses import pause_ends_ms, plan_stills

    info = media.probe(recorded)
    printed = [(line.at, line.text.strip()) for line in vhs_log if media.is_progress(line)]
    ends = pause_ends_ms(tape.commands, tape.pauses, printed, info.duration_ms)
    inserts, moving = plan_stills(tape.pauses, ends, media.freezes(recorded), info.frame_rate)
    moving += [pause for pause in tape.pauses if jobs.busy(pause) and pause not in moving]
    if moving:
        scenes = ", ".join(sorted({pause.scene_id or "end card" for pause in moving}))
        message = f"the screen was not still at the end of a pause in: {scenes}"
        if not planned.draft:
            raise RenderError(
                message,
                hint="Let the scene `wait` for the command's last output before the pause, "
                "or set `fast: false` on the scene.",
            )
        say(f"{message}; the draft freezes the picture there anyway")
    media.repeat_frames(
        recorded,
        [(insert.frame, insert.count) for insert in inserts],
        video,
        fast=planned.draft,
    )
    return inserts


@dataclass(frozen=True)
class BuildResult:
    """What ``build`` produced and how well it matched the timeline."""

    output: Path
    expected_ms: int
    video_ms: int
    placements: tuple[Placement, ...]
    # Placed per scene (see narratty.sync): the scenes whose narration ran over, else None.
    overruns: tuple[Overrun, ...] | None = None

    @property
    def drift(self) -> float:
        """Relative difference between the rendered and the planned length."""
        return (self.video_ms - self.expected_ms) / self.expected_ms if self.expected_ms else 0.0


def place_clips(planned: Plan, video_ms: int) -> list[Placement]:
    """Clip positions, stretched by the ratio of rendered to planned length.

    The fallback when the recording has no scene markers (see ``narratty.sync``).
    """
    starts = scaled_starts(planned, video_ms)
    return [Placement(clip.scene_id, clip.path, starts[clip.scene_id]) for clip in planned.clips]


def scaled_starts(planned: Plan, video_ms: int) -> dict[str, int]:
    """Narration start of each visible scene, stretched like :func:`place_clips`."""
    return linear_starts(planned.timeline, video_ms)


def subtitle_mode(planned: Plan, override: str | None) -> str:
    """``--subtitles``, else ``burn`` for a draft, else the spec's ``subtitles``."""
    return override or ("burn" if planned.draft else planned.spec.subtitles)


def narrations(planned: Plan, starts: dict[str, int]) -> list[Narrated]:
    """Each narration as written in the spec, at ``starts``, with its planned length."""
    return [
        Narrated(scene.narration or "", starts[scene.id], planned.timeline.scene(scene.id).audio_ms)
        for scene in planned.spec.narrated_scenes
    ]


def has_overlays(spec: Spec) -> bool:
    """Whether any scene shows an overlay."""
    return any(isinstance(action, ShowOverlay) for scene in spec.scenes for action in scene.actions)


def has_browsers(spec: Spec) -> bool:
    """Whether any scene shows a browser or a slide."""
    return any(
        isinstance(action, ShowBrowser | ShowSlide) for scene in spec.scenes for action in scene.actions
    )


def overlay_images(
    planned: Plan, video_ms: int, work: Path, workspace: Path, layout: timelapse.Layout | None = None
) -> list[OverlayImage]:
    """The spec's browser views and overlays drawn into ``work``.

    Timed where their cues were recorded (``layout``), else like :func:`place_clips`.
    Browser views come first, so overlays are drawn on top of them.
    """
    from narratty.render import browser
    from narratty.render.overlays import images, planned_times, scaled, schedule
    from narratty.render.script import build_script

    spec = planned.spec
    if not (has_overlays(spec) or has_browsers(spec)):
        return []
    if layout is not None:
        times, scale = layout.scene_starts_ms | layout.cues_ms, 1.0
    else:
        times = planned_times(build_script(spec, planned.timeline))
        scale = video_ms / planned.timeline.total_ms if planned.timeline.total_ms else 1.0
    views = browser.scaled(browser.schedule(spec, times), scale)
    shots = browser.shoot(spec, views, workspace, work / "browser")
    shown = scaled(schedule(spec, times), scale)
    return browser.images(shots, browser.bar_height(spec.terminal)) + images(spec, shown, work / "overlays")


def _cache_exclusions(ws: PreparedWorkspace, paths: Sequence[Path]) -> frozenset[Path]:
    excluded = set()
    for path in paths:
        resolved = path.resolve()
        if resolved.is_relative_to(ws.path.resolve()):
            excluded.add(resolved)
        elif resolved.is_relative_to(ws.source.resolve()):
            excluded.add(ws.path / resolved.relative_to(ws.source.resolve()))
    try:
        relative_paths = json.loads(os.environ.get("NARRATTY_SCENE_CACHE_EXCLUSIONS", "[]"))
        for value in relative_paths:
            relative = Path(value)
            if not relative.is_absolute() and ".." not in relative.parts:
                excluded.add(ws.path / relative)
    except (ValueError, TypeError):
        pass
    return frozenset(excluded)


@dataclass
class FreshFootage:
    """The fresh recording joined to cached footage, and its markers (see render_silent)."""

    video: Path | None = None
    positions: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class SceneCachePlan:
    """The cache entries and reusable prefix selected for a build."""

    cache: SceneCache
    keys: dict[str, str]
    prefix: SceneRecording | None
    replay: frozenset[str]


def _scene_cache_plan(
    planned: Plan,
    ws: PreparedWorkspace,
    output: Path,
    work: Path,
    bridge: Sequence[str] | None,
    *,
    fast: bool,
    refresh: bool,
    log: Log,
) -> SceneCachePlan | None:
    from narratty.render.scene_cache import SceneCache, recording_context, scene_keys

    visible = [scene.id for scene in planned.spec.scenes if not scene.hidden]
    unsupported = (
        planned.draft
        or fast
        or planned.timeline.has_timelapse
        or has_overlays(planned.spec)
        or has_browsers(planned.spec)
        or bridge is not None
        or any(scene.fast for scene in planned.spec.scenes)
        or sum(not scene.hidden for scene in planned.spec.scenes) < 2
    )
    if unsupported:
        log("scene cache unavailable for this build; recording all scenes")
        return None
    if ws.snapshot_root is not None:
        # The snapshot directory is new each build and shows in prompts and output. Keying
        # to it would never hit, and leaving it out would mix footage from different paths.
        log(
            "scene cache unavailable for a native workspace snapshot, which gets a new path "
            "each build; use --workspace-mode rw or a container runtime"
        )
        return None
    cache = SceneCache(cache_dir())
    exclusions = _cache_exclusions(
        ws,
        (
            planned.spec_path,
            output,
            output.with_suffix(".srt"),
            output.with_suffix(".vtt"),
            output.with_suffix(".artifacts"),
            work,
            cache_dir(),
        ),
    )
    context = recording_context(ws.path, exclude=exclusions, passthrough=planned.spec.sandbox.env_passthrough)
    keys = scene_keys(planned.spec, planned.timeline, context)
    selected = None
    replay: frozenset[str] = frozenset()
    if not refresh:
        for index, scene_id in enumerate(visible[:-1]):
            candidate = cache.get(keys[scene_id])
            prefix = visible[: index + 1]
            if candidate is None:
                missing = "unreadable entry" if cache.has(keys[scene_id]) else "no matching entry"
                log(f"scene cache miss through {scene_id}: {missing}")
                continue
            if any(name not in candidate.starts_ms for name in prefix):
                log(f"scene cache entry through {scene_id} is missing a scene boundary")
                continue
            if reason := _scene_recording_problem(candidate, prefix):
                log(f"scene cache entry through {scene_id} is incompatible: {reason}")
            else:
                selected, replay = candidate, frozenset(prefix)
    if selected is not None:
        log(f"reusing {len(replay)} cached scenes; replaying their commands hidden")
    return SceneCachePlan(cache, keys, selected, replay)


def _scene_recording_problem(candidate: SceneRecording, prefix: list[str]) -> str | None:
    """Whether cached footage can safely supply the given scene prefix."""
    starts = [candidate.starts_ms[name] for name in prefix]
    if starts != sorted(starts) or starts[-1] >= candidate.cut_ms:
        return "scene boundaries are not ordered before the cut"
    for part in candidate.parts:
        try:
            info = media.probe(part.video)
        except RenderError:
            return f"recording {part.video.name} is unreadable"
        if not info.has_video:
            return "recording has no video stream"
        if info.frame_rate <= 0:
            return "recording has no known frame rate"
        if info.duration_ms < part.end_ms:
            return f"recording ends at {info.duration_ms} ms before cut {part.end_ms} ms"
    return None


def build(
    spec_path: Path,
    output: Path | None = None,
    *,
    work_dir: Path | None = None,
    offline: bool = False,
    max_drift: float = DEFAULT_MAX_DRIFT,
    workspace: WorkspaceOptions | None = None,
    end_card: bool | None = None,
    subtitles: str | None = None,
    draft: bool = False,
    fast: bool = False,
    ignore_exit: bool = False,
    sandbox: SandboxRequest | None = None,
    log: Log | None = None,
    scene_cache: bool = False,
    refresh_scene_cache: bool = False,
) -> BuildResult:
    """Run the full pipeline and verify the result.

    ``subtitles`` overrides the spec's ``subtitles`` (a draft burns them in by default).
    ``fast`` fills long pauses with still frames instead of recording them (a draft
    always does). ``ignore_exit`` stops checking exit codes where the spec sets no
    ``expect_exit``. ``sandbox`` carries the command line's sandbox and environment choices.
    """
    say = log or (lambda _message: None)
    output = (output or default_output(spec_path, ".draft.mp4" if draft else ".mp4")).resolve()
    say("estimating narration" if draft else "synthesizing narration")
    planned = plan(spec_path, offline=offline, end_card=end_card, draft=draft, log=say)
    mode = subtitle_mode(planned, subtitles)
    warn_unenforced_sandbox(planned.spec, say, sandbox)
    with (
        work_directory(work_dir) as work,
        workspace_for(planned, workspace or WorkspaceOptions(), sandbox, log=say) as ws,
        environment_bridge(planned, ws, sandbox, say) as bridge,
    ):
        cache = (
            _scene_cache_plan(
                planned, ws, output, work, bridge, fast=fast, refresh=refresh_scene_cache, log=say
            )
            if scene_cache
            else None
        )
        say(f"recording {len(planned.timeline.scenes)} scenes with VHS")
        silent = work / "silent.mp4"
        render_options: dict[str, Any] = {}
        fresh = FreshFootage()
        if cache is not None:
            render_options = {
                "cache_markers": True,
                "cached_prefix": cache.prefix,
                "replay_scenes": cache.replay,
                "fresh": fresh,
            }
        layout = render_silent(
            planned,
            silent,
            work,
            ws.path,
            bridge,
            fast=fast or draft,
            log=say,
            request=sandbox,
            **render_options,
        )
        video_ms = media.probe(silent).duration_ms
        if layout is None:
            expected_ms, wanted = planned.timeline.total_ms, scaled_starts(planned, video_ms)
        else:
            expected_ms = layout.expected_ms(planned.timeline)
            wanted = aligned_starts(
                planned, layout.scene_starts_ms, layout.narration_offsets_ms, layout.cues_ms
            )
        placements = [Placement(clip.scene_id, clip.path, wanted[clip.scene_id]) for clip in planned.clips]
        say("mixing narration")
        track = work / "narration.wav"
        used = build_track(placements, video_ms, track)
        placed = {p.scene_id: p.start_ms for p in used}
        starts = wanted | placed
        late = None if layout is None else _overruns(planned, layout, video_ms, placed, wanted, say)
        cues = cues_for(narrations(planned, starts))
        srt: Path | None = None
        if mode in ("track", "burn") and cues:
            srt = work / "subtitles.srt"
            srt.write_text(to_srt(cues), encoding="utf-8")
        if has_browsers(planned.spec):
            say("capturing browser views")
        overlays = overlay_images(planned, video_ms, work, ws.path, layout)
        if overlays:
            say(f"drawing {len(overlays)} overlays")
        media.mux(
            silent, track, output, subtitles=srt, burn=mode == "burn", overlays=overlays, fast=planned.draft
        )
        if mode == "files":
            SubtitleFiles.beside(output).write(cues)
        _export_artifacts(planned, ws.path, output, say)
        check_exits(planned, work, output, ignore_exit=ignore_exit)
        result = BuildResult(output, expected_ms, video_ms, tuple(used), late)
        if cache is not None and layout is not None:
            verify(result, max_drift=max_drift)
            try:
                _store_scenes(cache, planned, silent, layout, fresh)
            except OSError as error:  # a full disk or read-only cache must not fail the build
                say(f"scene cache not updated: {error}")
    verify(result, max_drift=max_drift)
    return result


def _overruns(
    planned: Plan,
    layout: timelapse.Layout,
    video_ms: int,
    placed: dict[str, int],
    wanted: dict[str, int],
    say: Log,
) -> tuple[Overrun, ...]:
    """Scenes whose narration runs past their end in the video; each is logged."""
    end = end_of_scenes(layout.cues_ms, video_ms)
    found = overruns(planned.timeline, layout.scene_starts_ms, end, placed, wanted)
    for item in found:
        say(f"warning: narration runs past the end of scene {item.describe()}")
    return tuple(found)


def _store_scenes(
    cache: SceneCachePlan, planned: Plan, silent: Path, layout: timelapse.Layout, fresh: FreshFootage
) -> None:
    """Add entries for the freshly recorded scenes (see narratty.render.scene_cache)."""
    keys = {scene.id: cache.keys[scene.id] for scene in planned.spec.scenes if not scene.hidden}
    if cache.prefix is None:
        cache.cache.put(keys, silent, layout.scene_starts_ms, layout.cues_ms["end"])
        return
    if fresh.video is None:
        return
    cache.cache.put(
        keys,
        fresh.video,
        layout.scene_starts_ms,
        layout.cues_ms["end"],
        base=cache.prefix,
        video_starts_ms={
            scene: fresh.positions[f"scene-{scene}"] for scene in keys if scene not in cache.replay
        },
        video_end_ms=fresh.positions["cue-end"],
    )


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


def place_clips_at(
    planned: Plan,
    scene_starts_ms: dict[str, int],
    offsets_ms: dict[str, int] | None = None,
    cues_ms: dict[str, int] | None = None,
) -> list[Placement]:
    """Clip positions at the recorded start of each scene (see :func:`aligned_starts`)."""
    starts = aligned_starts(planned, scene_starts_ms, offsets_ms, cues_ms)
    return [Placement(clip.scene_id, clip.path, starts[clip.scene_id]) for clip in planned.clips]


def aligned_starts(
    planned: Plan,
    scene_starts_ms: dict[str, int],
    offsets_ms: dict[str, int] | None = None,
    cues_ms: dict[str, int] | None = None,
) -> dict[str, int]:
    """Narration starts relative to each scene's recorded start (see ``narratty.sync``).

    ``offsets_ms`` overrides the planned narration offset (timelapse scenes); a recorded
    narration cue in ``cues_ms`` places an ``after_actions`` narration where the actions
    actually ended.
    """
    return narration_starts(planned.timeline, scene_starts_ms, cues_ms, offsets_ms)


def build_cast(
    spec_path: Path,
    output: Path | None = None,
    *,
    work_dir: Path | None = None,
    offline: bool = False,
    workspace: WorkspaceOptions | None = None,
    end_card: bool | None = None,
    subtitles: str | None = None,
    fast: bool = False,
    ignore_exit: bool = False,
    sandbox: SandboxRequest | None = None,
    log: Log | None = None,
) -> BuildResult:
    """Record an asciicast with a narration track and a page that plays both.

    ``output`` is the HTML page; the ``.cast`` and ``.mp3`` are written beside it, and
    with any ``subtitles`` mode but ``none`` also the ``.srt`` and ``.vtt``.
    Clips are placed at the recorded start of their scene, so there is no drift to check.
    ``fast`` skips the rest of a long pause once the output has been quiet for a moment.
    ``ignore_exit`` as in :func:`build`.
    """
    from narratty.render.player import player_page, player_theme

    say = log or (lambda _message: None)
    outputs = CastOutputs((output or default_output(spec_path, ".html")).resolve())
    say("synthesizing narration")
    planned = plan(spec_path, offline=offline, end_card=end_card, log=say)
    warn_unenforced_sandbox(planned.spec, say, sandbox)
    spec = planned.spec
    with (
        work_directory(work_dir) as work,
        workspace_for(planned, workspace or WorkspaceOptions(), sandbox, log=say) as ws,
        environment_bridge(planned, ws, sandbox, say) as bridge,
    ):
        say(f"recording {len(planned.timeline.scenes)} scenes as an asciicast")
        recording = _record_cast(planned, work, ws, bridge, sandbox, fast=fast)
        outputs.page.parent.mkdir(parents=True, exist_ok=True)
        outputs.cast.write_text(recording.cast, encoding="utf-8")
        say("mixing narration")
        track = work / "narration.wav"
        placements = place_clips_at(
            planned, recording.scene_starts_ms, recording.narration_offsets_ms, recording.cues_ms
        )
        used = build_track(placements, recording.duration_ms, track)
        media.encode_mp3(track, outputs.audio)
        if subtitle_mode(planned, subtitles) != "none":
            starts = {p.scene_id: p.start_ms for p in used}
            SubtitleFiles.beside(outputs.page).write(cues_for(narrations(planned, starts)))
        overlays: list[dict[str, Any]] = []
        times = recording.scene_starts_ms | recording.cues_ms
        if has_overlays(spec):
            from narratty.render.overlays import page_overlays, schedule

            overlays = page_overlays(schedule(spec, times), spec.terminal)
        views: list[dict[str, Any]] = []
        if has_browsers(spec):
            from narratty.render import browser

            say("capturing browser views")
            shots = browser.shoot(spec, browser.schedule(spec, times), ws.path, work / "browser")
            views = browser.page_views(shots, spec.terminal)
        page = player_page(
            spec.meta.title,
            recording.cast,
            outputs.audio,
            theme=player_theme(spec.terminal.theme),
            overlays=overlays,
            browsers=views,
        )
        outputs.page.write_text(page, encoding="utf-8")
        _export_artifacts(planned, ws.path, outputs.page, say)
        check_exits(planned, work, outputs.page, ignore_exit=ignore_exit)
    return BuildResult(outputs.page, planned.timeline.total_ms, recording.duration_ms, tuple(used))


def _record_cast(
    planned: Plan,
    work: Path,
    ws: PreparedWorkspace,
    bridge: list[str] | None,
    sandbox: SandboxRequest | None,
    *,
    fast: bool,
) -> Recording:
    """Play the script in a pseudo-terminal; the exit log ends up in ``work``."""
    from narratty.bridge import shim_env
    from narratty.render.cast import record
    from narratty.render.script import build_script

    spec = planned.spec
    env = {**os.environ, **recording_env(spec)}
    placement = placement_for(planned, work, bridge, sandbox)
    if placement.bridged:
        env = shim_env(work / "shims", bridge or [], env)
    exit_log = fresh_exit_log(work, bridge)
    recording = record(
        build_script(spec, planned.timeline, exit_log=exit_log, placement=placement),
        terminal=spec.terminal,
        cwd=ws.path,
        env=env,
        title=spec.meta.title,
        fast=fast,
        shell=placement.shell(spec),
    )
    collect_exit_log(bridge, exit_log, work)
    return recording


@dataclass(frozen=True)
class CheckResult:
    """How many commands ran and how many of them had their output compared."""

    commands: int
    compared: int


def check(
    spec_path: Path,
    *,
    work_dir: Path | None = None,
    workspace: WorkspaceOptions | None = None,
    ignore_exit: bool = False,
    sandbox: SandboxRequest | None = None,
    log: Log | None = None,
) -> CheckResult:
    """Run the spec's commands as a recording would, without video, voice or end card.

    Fails when a command's exit code contradicts its ``expect_exit`` (``ignore_exit`` as
    in :func:`build`) or its output its ``expect_output``. Records how long each ``run``
    took for later plans (see ``narratty.durations``).
    """
    from narratty.render import outputs

    say = log or (lambda _message: None)
    planned = plan(spec_path, end_card=False, draft=True, log=say)
    # In the editor layout the shell's output reaches the recorder through tmux, redrawn.
    editor = planned.spec.terminal.layout == "editor"
    if editor:
        say("output is not compared in the editor layout; checking exit codes only")
    warn_unenforced_sandbox(planned.spec, say, sandbox)
    with (
        work_directory(work_dir) as work,
        workspace_for(planned, workspace or WorkspaceOptions(), sandbox, log=say) as ws,
        environment_bridge(planned, ws, sandbox, say) as bridge,
    ):
        say(f"running {len(planned.timeline.scenes)} scenes")
        recording = _record_cast(planned, work, ws, bridge, sandbox, fast=True)
        check_exits(planned, work, None, ignore_exit=ignore_exit)
        _record_durations(planned.spec, recording, say)
    if not editor:
        outputs.check(planned.spec, recording.submitted)
    runs = [action for scene in planned.spec.scenes for action in scene.actions if isinstance(action, Run)]
    return CheckResult(len(runs), 0 if editor else len(outputs.expectations(planned.spec)))


def _record_durations(spec: Spec, recording: Recording, say: Log) -> None:
    """Keep how long each ``run`` took (see ``narratty.durations``); never fails the check."""
    from narratty import durations

    measured = durations.match_runs(spec, recording.took_ms)
    if not measured:
        return
    try:
        durations.DurationStore(cache_dir()).record(spec, measured)
    except OSError as error:
        say(f"command durations not recorded: {error}")
        return
    slow = durations.describe(spec, measured)
    say(
        f"recorded how long {len(measured)} commands took"
        + (f"; plans now wait for the slow ones: {slow}" if slow else "")
    )


def verify(result: BuildResult, *, max_drift: float) -> None:
    """Fail when the output lacks a stream or drifted beyond ``max_drift``.

    With per-scene placement (``result.overruns`` set), drift is judged per scene: a
    narration may run past its scene's end by ``max_drift`` of its length. Otherwise
    the video's length is compared with the plan.
    """
    info = media.probe(result.output)
    if not (info.has_video and info.has_audio):
        raise RenderError(f"{result.output} is missing its {'audio' if info.has_video else 'video'} stream")
    if result.overruns is not None:
        _verify_scenes(result.overruns, max_drift)
    elif abs(result.drift) > max_drift:
        raise SyncError(
            f"the video is {result.video_ms / 1000:.2f}s long but the timeline planned "
            f"{result.expected_ms / 1000:.2f}s ({result.drift:+.0%})",
            hint="A command or `wait` took longer than its scene; add a `hold` or move slow "
            "commands into a hidden scene.",
        )


def _verify_scenes(found: Sequence[Overrun], max_drift: float) -> None:
    if failing := too_far(found, max_drift):
        raise SyncError(
            "narration runs past the end of its scene in: " + ", ".join(item.describe() for item in failing),
            hint="A scene recorded shorter than planned usually means VHS dropped frames on a busy "
            "machine; build again with less load.",
        )
