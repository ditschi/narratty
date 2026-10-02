"""The whole pipeline: spec → narration clips → timeline → tape → silent video → mp4."""

from __future__ import annotations

import dataclasses
import itertools
import os
import shlex
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, ExitStack, contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from narratty.cache import AudioCache
from narratty.end_card import with_end_card
from narratty.errors import RenderError, SyncError
from narratty.paths import cache_dir, data_dir
from narratty.render import media, timelapse
from narratty.render.narration import Placement, build_track
from narratty.render.script import CARD, END_CUE, HEAD, TAIL
from narratty.render.subtitles import Narrated, SubtitleFiles, cues_for, to_srt
from narratty.spec import load_spec
from narratty.spec.model import ShowBrowser, ShowOverlay, Spec
from narratty.timeline import Timeline, build_timeline
from narratty.tts.lexicon import load_lexicon
from narratty.tts.registry import get_provider
from narratty.tts.synth import Clip, synthesize_spec
from narratty.workspace import PreparedWorkspace, export_artifacts, prepare_workspace

if TYPE_CHECKING:
    from narratty.cache import Segment, SegmentCache
    from narratty.container import SandboxRequest
    from narratty.incremental import Job, Link
    from narratty.render.overlays import OverlayImage
    from narratty.render.pauses import Insert, JobWatch, Pause
    from narratty.render.script import HelperPlacement
    from narratty.render.tape import Tape
    from narratty.spec.model import Environment

SPEC_SUFFIXES = (".narratty.yaml", ".narratty.yml", ".yaml", ".yml")
DEFAULT_MAX_DRIFT = 0.10
# VHS ends a recording a little early or late; on a short video (one scene) that is a large share.
MIN_DRIFT_MS = 250

Log = Callable[[str], None]


def default_output(spec_path: Path, suffix: str = ".mp4") -> Path:
    """``demo.narratty.yaml`` → ``demo.mp4`` next to the spec."""
    name = spec_path.name
    for known in SPEC_SUFFIXES:
        if name.endswith(known):
            return spec_path.with_name(name.removesuffix(known) + suffix)
    return spec_path.with_suffix(suffix)


def video_suffix(*, draft: bool = False, scenes: bool = False) -> str:
    """Suffix of the default output: ``.mp4``, ``.draft.mp4``, ``.scenes.mp4`` or ``.scenes.draft.mp4``."""
    return (".scenes" if scenes else "") + (".draft.mp4" if draft else ".mp4")


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
    ``narratty.draft``).
    """
    spec = with_end_card(load_spec(spec_path), end_card)
    if draft:
        from narratty.draft import estimated_audio_ms

        return Plan(spec_path, spec, (), build_timeline(spec, estimated_audio_ms(spec)), draft=True)
    provider = get_provider(spec.tts.provider, data_dir())
    lexicon = load_lexicon(spec_path, spec.tts)
    clips = synthesize_spec(
        spec, provider, AudioCache(cache_dir()), download=not offline, lexicon=lexicon, log=log
    )
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


def check_exits(planned: Plan, work: Path, output: Path, *, ignore_exit: bool = False) -> None:
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
) -> timelapse.Layout | None:
    """Write the tape into ``work`` and record it with VHS in ``workspace`` into ``video``.

    With a ``bridge`` the shell runs in the project environment.

    ``fast`` records long pauses briefly and fills them with still frames (see
    ``narratty.render.pauses``), except in scenes with ``fast: false``; scenes with
    ``fast: true`` do so without it. A pause whose screen was not still fails the build,
    except in a draft, which only logs it.

    With timelapse scenes, overlays or browser views, the tape also takes markers: the
    timelapse scenes are sped up into ``video`` and the returned layout says where each
    scene and cue landed.
    """
    from narratty.bridge import shim_env
    from narratty.draft import FRAMERATE as DRAFT_FRAMERATE
    from narratty.render.tape import FRAMERATE, build_tape, uses_fast

    tape_path = work / "scene.tape"
    filling = uses_fast(planned.spec, fast)
    framerate = DRAFT_FRAMERATE if planned.draft else FRAMERATE
    measured = planned.timeline.has_timelapse or has_overlays(planned.spec) or has_browsers(planned.spec)
    marks = (work / "marks").resolve() if measured else None
    recording = work / "recording.mp4" if marks or filling else video
    if marks:
        marks.mkdir(parents=True, exist_ok=True)
    tape = build_tape(
        planned.spec,
        planned.timeline,
        recording.resolve(),
        framerate=framerate,
        marks=marks,
        exit_log=(exit_log := fresh_exit_log(work, bridge)),
        placement=(placement := placement_for(planned, work, bridge, request)),
        fast=fast,
    )
    tape_path.write_text(tape.text, encoding="utf-8")
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
    collect_exit_log(bridge, exit_log, work)
    if not recording.is_file():
        raise RenderError(f"VHS finished but wrote no video to {recording}")
    if jobs is None and marks is None:
        return None
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

    positions = timelapse.marker_positions(vhs_log, marks, recorded.duration_ms)
    positions = shift_positions(positions, inserts, recorded.frame_rate)
    layout = timelapse.layout(planned.timeline, positions)
    if layout.segments:
        timelapse.speed_up(recording, layout.segments, video, framerate=framerate)
    else:
        recording.replace(video)
    return layout


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
    _check_still(planned, moving, say)
    media.repeat_frames(
        recorded,
        [(insert.frame, insert.count) for insert in inserts],
        video,
        fast=planned.draft,
    )
    return inserts


def _check_still(planned: Plan, moving: Sequence[Pause], say: Log) -> None:
    """Fail (a draft: only log) when a shortened pause ended while the screen changed."""
    if not moving:
        return
    scenes = ", ".join(sorted({pause.scene_id or "end card" for pause in moving}))
    message = f"the screen was not still at the end of a pause in: {scenes}"
    if not planned.draft:
        raise RenderError(
            message,
            hint="Let the scene `wait` for the command's last output before the pause, "
            "or set `fast: false` on the scene.",
        )
    say(f"{message}; the draft freezes the picture there anyway")


def record_sections(
    planned: Plan,
    links: Sequence[Link],
    job: Job,
    work: Path,
    workspace: Path,
    bridge: Sequence[str] | None = None,
    *,
    fast: bool,
    cache: SegmentCache,
    log: Log,
    request: SandboxRequest | None = None,
) -> dict[str, Segment]:
    """Record the sections ``job`` names with VHS in ``workspace``; one video each in ``work``.

    Earlier scenes are replayed unrecorded (see ``narratty.incremental``). When a quick
    replay left a command running, the scene is remembered to replay at its own pace
    and :class:`~narratty.incremental.UnsafeReplay` is raised.
    """
    from narratty.bridge import shim_env
    from narratty.cache import Segment, SegmentMeta
    from narratty.draft import FRAMERATE as DRAFT_FRAMERATE
    from narratty.incremental import UnsafeReplay, owner
    from narratty.render.pauses import JobWatch, pause_ends_ms, plan_stills
    from narratty.render.tape import FRAMERATE, build_tape

    if job.partial is None:
        return {}
    framerate = DRAFT_FRAMERATE if planned.draft else FRAMERATE
    marks = (work / "marks").resolve()
    shutil.rmtree(marks, ignore_errors=True)
    marks.mkdir(parents=True)
    recording = work / "recording.mp4"
    tape = build_tape(
        planned.spec,
        planned.timeline,
        recording.resolve(),
        framerate=framerate,
        marks=marks,
        exit_log=(exit_log := fresh_exit_log(work, bridge)),
        placement=(placement := placement_for(planned, work, bridge, request)),
        fast=fast,
        partial=job.partial,
    )
    tape_path = work / "scene.tape"
    tape_path.write_text(tape.text, encoding="utf-8")
    watched = [*tape.pauses, *tape.replays]
    jobs = JobWatch(watched) if watched else None
    extra_env = recording_env(planned.spec)
    if placement.bridged:
        extra_env["PATH"] = shim_env(work / "shims", bridge or [], os.environ)["PATH"]
    vhs_log = media.run_vhs(
        tape_path, workspace, extra_env=extra_env, on_line=_progress_watch(jobs) if jobs else None
    )
    collect_exit_log(bridge, exit_log, work)
    if jobs is not None and (unsafe := [p.section for p in tape.replays if p.section and jobs.busy(p)]):
        contents = {link.label: link.content for link in links}
        for label in dict.fromkeys(unsafe):
            cache.mark_realtime(contents[label])
        raise UnsafeReplay(list(dict.fromkeys(unsafe)))
    if not recording.is_file():
        raise RenderError(f"VHS finished but wrote no video to {recording}")
    info = media.probe(recording)
    positions: dict[str, int] = {}
    if any(label != HEAD for label in job.recorded):
        positions = timelapse.marker_positions(vhs_log, marks, info.duration_ms)
    pause_ends: list[tuple[str | None, int]] = []
    if tape.pauses and jobs is not None:
        printed = [(line.at, line.text.strip()) for line in vhs_log if media.is_progress(line)]
        ends = pause_ends_ms(tape.commands, tape.pauses, printed, info.duration_ms)
        _, moving = plan_stills(tape.pauses, ends, media.freezes(recording), info.frame_rate)
        moving += [pause for pause in tape.pauses if jobs.busy(pause) and pause not in moving]
        _check_still(planned, moving, log)
        pause_ends = [(pause.section, end) for pause, end in zip(tape.pauses, ends, strict=True)]
    starts = [_section_start(positions, label) for label in job.recorded]
    segments: dict[str, Segment] = {}
    for index, label in enumerate(job.recorded):
        start = starts[index]
        end = max(start, starts[index + 1] if index + 1 < len(starts) else info.duration_ms)
        pauses = tuple(max(0, ms - start) for section, ms in pause_ends if section == label)
        marked = {name: max(0, ms - start) for name, ms in positions.items() if owner(name) == label}
        if (end - start) * framerate < 500:  # under half a frame: nothing was shown
            segments[label] = Segment(None, SegmentMeta(0, pauses, marked))
            continue
        piece = work / "sections" / f"{index:03d}.mp4"
        media.cut(recording, start, end, piece, fast=planned.draft)
        segments[label] = Segment(piece, SegmentMeta(media.probe(piece).duration_ms, pauses, marked))
    return segments


def _section_start(positions: dict[str, int], label: str) -> int:
    """Where a recorded section starts: the lead-in at once, the others at their marker."""
    if label == HEAD:
        return 0
    marker = {TAIL: f"cue-{END_CUE}", CARD: "card"}.get(label, f"scene-{label}")
    if marker not in positions:
        raise RenderError(f"VHS did not log the marker {marker!r}")
    return positions[marker]


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
    starts = scaled_starts(planned, video_ms)
    return [Placement(clip.scene_id, clip.path, starts[clip.scene_id]) for clip in planned.clips]


def scaled_starts(planned: Plan, video_ms: int) -> dict[str, int]:
    """Narration start of each narrated scene, stretched like :func:`place_clips`."""
    scale = video_ms / planned.timeline.total_ms if planned.timeline.total_ms else 1.0
    return {
        scene.id: round(planned.timeline.scene(scene.id).audio_start_ms * scale)
        for scene in planned.spec.narrated_scenes
    }


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
    """Whether any scene shows a browser."""
    return any(isinstance(action, ShowBrowser) for scene in spec.scenes for action in scene.actions)


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
    clean: bool = False,
    scenes: Sequence[str] = (),
    log: Log | None = None,
) -> BuildResult:
    """Run the full pipeline and verify the result.

    ``subtitles`` overrides the spec's ``subtitles`` (a draft burns them in by default).
    ``fast`` fills long pauses with still frames instead of recording them (a draft
    always does). ``ignore_exit`` stops checking exit codes where the spec sets no
    ``expect_exit``. ``sandbox`` carries the command line's sandbox and environment choices.

    Scenes recorded before are taken from the cache unless ``clean`` (see
    ``narratty.incremental``). ``scenes`` (ranges, see
    :func:`~narratty.incremental.select_scenes`) builds a video of only those scenes.
    """
    from narratty.incremental import UnsafeReplay, select_scenes

    say = log or (lambda _message: None)
    say("estimating narration" if draft else "synthesizing narration")
    planned = plan(spec_path, offline=offline, end_card=end_card, draft=draft, log=say)
    selected = select_scenes(planned.spec, scenes) if scenes else None
    output = (output or default_output(spec_path, video_suffix(draft=draft, scenes=bool(selected)))).resolve()
    options = _BuildOptions(
        work_dir, max_drift, workspace, subtitles, fast or draft, ignore_exit, sandbox, clean
    )
    for attempt in itertools.count():
        try:
            return _build(planned, output, selected, options, say)
        except UnsafeReplay as unsafe:
            if attempt >= len(planned.spec.scenes):
                raise
            say(
                f"{unsafe}; recording again, replaying {', '.join(unsafe.scenes)} at its own pace from now on"
            )
    raise AssertionError("unreachable")  # pragma: no cover


@dataclass(frozen=True)
class _BuildOptions:
    work_dir: Path | None
    max_drift: float
    workspace: WorkspaceOptions | None
    subtitles: str | None
    fast: bool
    ignore_exit: bool
    sandbox: SandboxRequest | None
    clean: bool


def _build(
    planned: Plan, output: Path, selected: Sequence[str] | None, options: _BuildOptions, say: Log
) -> BuildResult:
    """One attempt of :func:`build`: record what the cache lacks, join, mix and verify."""
    from narratty import incremental
    from narratty.cache import SegmentCache
    from narratty.draft import FRAMERATE as DRAFT_FRAMERATE
    from narratty.render.tape import FRAMERATE

    out = planned if selected is None else incremental.select_plan(planned, selected)
    mode = subtitle_mode(out, options.subtitles)
    sandbox = options.sandbox
    warn_unenforced_sandbox(planned.spec, say, sandbox)
    framerate = DRAFT_FRAMERATE if planned.draft else FRAMERATE
    cache = SegmentCache(cache_dir())
    links = incremental.chain(planned, fast=options.fast, framerate=framerate)
    labels = incremental.needed(planned, selected)
    run_all = incremental.runs_everything(out.spec)
    job = incremental.schedule(planned, links, labels, cache, clean=options.clean, run_all=run_all)
    keyed = {link.label: link for link in links}
    with ExitStack() as stack:
        work = stack.enter_context(work_directory(options.work_dir))
        ws = None
        if job.partial is not None or has_browsers(out.spec):
            ws = stack.enter_context(
                workspace_for(planned, options.workspace or WorkspaceOptions(), sandbox, log=say)
            )
        recorded: dict[str, Segment] = {}
        if job.partial is not None and ws is not None:
            bridge = stack.enter_context(environment_bridge(planned, ws, sandbox, say))
            say(_recording_message(job, labels))
            recorded = record_sections(
                planned,
                links,
                job,
                work,
                ws.path,
                bridge,
                fast=options.fast,
                cache=cache,
                log=say,
                request=sandbox,
            )
        else:
            say("every scene is cached, nothing to record")
        silent = work / "silent.mp4"
        parts = [(keyed[label], recorded.get(label) or job.cached[label]) for label in labels]
        layout = incremental.stitch(out, parts, silent, work, framerate=framerate)
        video_ms = media.probe(silent).duration_ms
        expected_ms = layout.expected_ms(out.timeline)
        placements = place_clips_at(out, layout.scene_starts_ms, layout.narration_offsets_ms)
        say("mixing narration")
        track = work / "narration.wav"
        used = build_track(placements, video_ms, track)
        starts = scaled_starts(out, video_ms) | {p.scene_id: p.start_ms for p in used}
        cues = cues_for(narrations(out, starts))
        srt: Path | None = None
        if mode in ("track", "burn") and cues:
            srt = work / "subtitles.srt"
            srt.write_text(to_srt(cues), encoding="utf-8")
        if has_browsers(out.spec):
            say("capturing browser views")
        overlays = overlay_images(out, video_ms, work, ws.path if ws else work, layout)
        if overlays:
            say(f"drawing {len(overlays)} overlays")
        media.mux(
            silent, track, output, subtitles=srt, burn=mode == "burn", overlays=overlays, fast=out.draft
        )
        if mode == "files":
            SubtitleFiles.beside(output).write(cues)
        if ws is not None:
            _export_artifacts(out, ws.path, output, say)
        if job.partial is not None:
            ran = dataclasses.replace(planned, spec=incremental.ran_spec(planned.spec, job.partial))
            check_exits(ran, work, output, ignore_exit=options.ignore_exit)
        result = BuildResult(output, expected_ms, video_ms, tuple(used))
        verify(result, max_drift=options.max_drift)
        for label, segment in recorded.items():
            cache.put(keyed[label].key, segment.video, segment.meta)
    return result


def _recording_message(job: Job, labels: Sequence[str]) -> str:
    """``recording 3 of 7 scenes with VHS (4 from the cache)``."""
    shown = [label for label in labels if label not in (HEAD, TAIL, CARD)]
    recorded = [label for label in job.recorded if label not in (HEAD, TAIL, CARD)]
    cached = len(shown) - len(recorded)
    return f"recording {len(recorded)} of {len(shown)} scenes with VHS" + (
        f" ({cached} from the cache)" if cached else ""
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
    planned: Plan, scene_starts_ms: dict[str, int], offsets_ms: dict[str, int] | None = None
) -> list[Placement]:
    """Clip positions at the recorded start of each scene.

    ``offsets_ms`` overrides the planned narration offset (timelapse scenes).
    """
    offsets = offsets_ms or {}
    return [
        Placement(
            clip.scene_id,
            clip.path,
            scene_starts_ms[clip.scene_id]
            + offsets.get(clip.scene_id, planned.timeline.scene(clip.scene_id).audio_offset_ms),
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
    subtitles: str | None = None,
    fast: bool = False,
    ignore_exit: bool = False,
    sandbox: SandboxRequest | None = None,
    scenes: Sequence[str] = (),
    log: Log | None = None,
) -> BuildResult:
    """Record an asciicast with a narration track and a page that plays both.

    ``output`` is the HTML page; the ``.cast`` and ``.mp3`` are written beside it, and
    with any ``subtitles`` mode but ``none`` also the ``.srt`` and ``.vtt``.
    Clips are placed at the recorded start of their scene, so there is no drift to check.
    ``fast`` skips the rest of a long pause once the output has been quiet for a moment.
    ``ignore_exit`` as in :func:`build`. ``scenes`` records only those scenes (ranges,
    see :func:`~narratty.incremental.select_scenes`); the earlier ones run unrecorded.
    """
    from narratty.bridge import shim_env
    from narratty.incremental import needed, ran_spec, select_plan, select_scenes
    from narratty.render.cast import record
    from narratty.render.player import player_page, player_theme
    from narratty.render.script import Partial, build_script

    say = log or (lambda _message: None)
    say("synthesizing narration")
    planned = plan(spec_path, offline=offline, end_card=end_card, log=say)
    selected = select_scenes(planned.spec, scenes) if scenes else None
    suffix = ".scenes.html" if selected else ".html"
    outputs = CastOutputs((output or default_output(spec_path, suffix)).resolve())
    out, partial = planned, None
    if selected is not None:
        out, labels = select_plan(planned, selected), needed(planned, selected)
        realtime = frozenset(scene.id for scene in planned.spec.scenes if scene.replay == "realtime")
        partial = Partial(frozenset(labels), labels[-1], realtime)
    warn_unenforced_sandbox(planned.spec, say, sandbox)
    spec = out.spec
    with (
        work_directory(work_dir) as work,
        workspace_for(planned, workspace or WorkspaceOptions(), sandbox, log=say) as ws,
        environment_bridge(planned, ws, sandbox, say) as bridge,
    ):
        say(f"recording {len(out.timeline.scenes)} scenes as an asciicast")
        env = {**os.environ, **recording_env(spec)}
        placement = placement_for(planned, work, bridge, sandbox)
        if placement.bridged:
            env = shim_env(work / "shims", bridge or [], env)
        recording = record(
            build_script(
                planned.spec,
                planned.timeline,
                exit_log=(exit_log := fresh_exit_log(work, bridge)),
                placement=placement,
                partial=partial,
            ),
            terminal=spec.terminal,
            cwd=ws.path,
            env=env,
            title=spec.meta.title,
            fast=fast,
            shell=placement.shell(spec),
        )
        collect_exit_log(bridge, exit_log, work)
        outputs.page.parent.mkdir(parents=True, exist_ok=True)
        outputs.cast.write_text(recording.cast, encoding="utf-8")
        say("mixing narration")
        track = work / "narration.wav"
        placements = place_clips_at(out, recording.scene_starts_ms, recording.narration_offsets_ms)
        used = build_track(placements, recording.duration_ms, track)
        media.encode_mp3(track, outputs.audio)
        if subtitle_mode(out, subtitles) != "none":
            starts = {p.scene_id: p.start_ms for p in used}
            SubtitleFiles.beside(outputs.page).write(cues_for(narrations(out, starts)))
        overlays: list[dict[str, Any]] = []
        times = {END_CUE: recording.duration_ms} | recording.scene_starts_ms | recording.cues_ms
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
        _export_artifacts(out, ws.path, outputs.page, say)
        ran = (
            planned if partial is None else dataclasses.replace(planned, spec=ran_spec(planned.spec, partial))
        )
        check_exits(ran, work, outputs.page, ignore_exit=ignore_exit)
    return BuildResult(outputs.page, out.timeline.total_ms, recording.duration_ms, tuple(used))


def verify(result: BuildResult, *, max_drift: float) -> None:
    """Fail when the output lacks a stream or drifted beyond ``max_drift``."""
    info = media.probe(result.output)
    if not (info.has_video and info.has_audio):
        raise RenderError(f"{result.output} is missing its {'audio' if info.has_video else 'video'} stream")
    if abs(result.drift) > max_drift and abs(result.video_ms - result.expected_ms) > MIN_DRIFT_MS:
        raise SyncError(
            f"the video is {result.video_ms / 1000:.2f}s long but the timeline planned "
            f"{result.expected_ms / 1000:.2f}s ({result.drift:+.0%})",
            hint="A command or `wait` took longer than its scene; add a `hold` or move slow "
            "commands into a hidden scene.",
        )
