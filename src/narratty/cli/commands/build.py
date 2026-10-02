"""``narratty build``: the full pipeline, from spec to narrated mp4 (or asciicast)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from narratty.cli.arguments import SpecArgument
from narratty.cli.options import (
    AllowDirtyOption,
    AllowHostOption,
    CleanOption,
    EndCardOption,
    EnvImageOption,
    IgnoreExitOption,
    ImageOption,
    KeepEnvOption,
    KeepWorkspaceOption,
    NetworkMode,
    NetworkOption,
    NoEnvOption,
    OfflineOption,
    RebuildEnvOption,
    RuntimeOption,
    ScenesOption,
    WorkspaceMode,
    WorkspaceModeOption,
    YesOption,
    sandbox_request,
)
from narratty.runtime import Runtime

if TYPE_CHECKING:
    from narratty.container import SandboxRequest


class OutputFormat(StrEnum):
    """Values of ``--format``."""

    MP4 = "mp4"
    CAST = "cast"


class SubtitleMode(StrEnum):
    """Values of ``--subtitles``."""

    NONE = "none"
    FILES = "files"
    TRACK = "track"
    BURN = "burn"


def build_command(
    spec: Path = SpecArgument,
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Where to write the video, or the HTML page for --format cast (default: next to the spec).",
    ),
    output_format: OutputFormat = typer.Option(
        OutputFormat.MP4,
        "--format",
        "-f",
        case_sensitive=False,
        help="mp4: narrated video. cast: asciicast + MP3 + an HTML page playing both.",
    ),
    work_dir: Path | None = typer.Option(
        None, "--work-dir", help="Keep the tape, silent video and narration track in this directory."
    ),
    max_drift: float = typer.Option(
        0.10,
        "--max-drift",
        min=0.0,
        help="Fail when the video's length differs from the plan by more (0.10 = 10%).",
    ),
    subtitles: SubtitleMode | None = typer.Option(
        None,
        "--subtitles",
        case_sensitive=False,
        help="Override the spec's subtitles: none, files (.srt/.vtt beside the output), "
        "track (soft track in the mp4) or burn (drawn into the video). --format cast writes files.",
    ),
    draft: bool = typer.Option(
        False,
        "--draft",
        help="Fast preview: no TTS (estimated narration lengths), 10 fps, half-size video, silent, "
        "narration burned in as subtitles, --fast. Writes <spec>.draft.mp4 by default.",
    ),
    fast: bool = typer.Option(
        False,
        "--fast",
        help="Don't wait out long pauses: once the screen is still, fill the rest with the "
        "last frame. Fails if a pause ends while the screen is still changing.",
    ),
    ignore_exit: bool = IgnoreExitOption,
    scenes: list[str] | None = ScenesOption,
    clean: bool = CleanOption,
    watch: bool = typer.Option(
        False,
        "--watch",
        "-w",
        help="Build again whenever the spec, its lexicon or files it uses change (Ctrl+C stops).",
    ),
    workspace_mode: WorkspaceMode | None = WorkspaceModeOption,
    keep_workspace: bool = KeepWorkspaceOption,
    allow_dirty: bool = AllowDirtyOption,
    network: NetworkMode | None = NetworkOption,
    allow_host: list[str] | None = AllowHostOption,
    env_image: str | None = EnvImageOption,
    no_env: bool = NoEnvOption,
    keep_env: bool = KeepEnvOption,
    rebuild_env: bool = RebuildEnvOption,
    yes: bool = YesOption,
    end_card: bool | None = EndCardOption,
    offline: bool = OfflineOption,
    runtime: Runtime = RuntimeOption,
    image: str | None = ImageOption,
) -> None:
    """Build the narrated video (or asciicast)."""
    from narratty.build import default_output, video_suffix
    from narratty.environment import EnvironmentOptions
    from narratty.errors import UsageError
    from narratty.ui.console import err

    cast = output_format is OutputFormat.CAST
    if draft and cast:
        raise UsageError("--draft only applies to --format mp4")
    ranges = scenes or []
    suffix = (
        (".scenes" if ranges else "") + ".html" if cast else video_suffix(draft=draft, scenes=bool(ranges))
    )
    env = EnvironmentOptions(no_env, env_image, keep_env, rebuild_env)
    request = sandbox_request(workspace_mode, keep_workspace, allow_dirty, network, allow_host, yes, env)

    def once() -> int:
        return _build_once(
            spec, output or default_output(spec, suffix), cast, request, ranges,
            output_format=output_format, work_dir=work_dir, max_drift=max_drift, subtitles=subtitles,
            draft=draft, fast=fast, ignore_exit=ignore_exit, clean=clean, end_card=end_card,
            offline=offline, runtime=runtime, image=image,
        )  # fmt: skip

    if not watch:
        if code := once():
            raise typer.Exit(code)
        return

    from narratty.watch import watch as watch_loop

    def say(message: str) -> None:
        err.print(f"[dim]{message}[/]", highlight=False)

    def build_once() -> None:
        once()  # a failed container run already printed why; wait for the next change

    watch_loop(spec, build_once, say=say)


def _build_once(  # noqa: PLR0913 - the command's options
    spec: Path,
    output: Path,
    cast: bool,
    request: SandboxRequest,
    ranges: list[str],
    *,
    output_format: OutputFormat,
    work_dir: Path | None,
    max_drift: float,
    subtitles: SubtitleMode | None,
    draft: bool,
    fast: bool,
    ignore_exit: bool,
    clean: bool,
    end_card: bool | None,
    offline: bool,
    runtime: Runtime,
    image: str | None,
) -> int:
    """Build once; the exit code of a container run that failed, else 0."""
    from narratty.build import build, build_cast
    from narratty.container import delegate
    from narratty.end_card import container_flag
    from narratty.ui.console import err, out

    code = delegate(
        "build",
        spec,
        runtime=runtime,
        image=image,
        output=output,
        work_dir=work_dir,
        extra_args=[
            "--format",
            output_format.value,
            "--max-drift",
            str(max_drift),
            container_flag(spec, end_card),
            *(["--subtitles", subtitles.value] if subtitles else []),
            *(["--draft"] if draft else []),
            *(["--fast"] if fast else []),
            *(["--ignore-exit"] if ignore_exit else []),
            *(["--clean"] if clean else []),
            *(arg for value in ranges for arg in ("--scenes", value)),
        ],
        sandbox=request,
        ignore_exit=ignore_exit,
    )
    if code is not None:
        return code

    with err.status("building") as status:

        def log(message: str) -> None:
            status.update(message)
            err.print(f"[dim]{message}[/]", highlight=False, soft_wrap=True)

        if cast:
            result = build_cast(
                spec,
                output,
                work_dir=work_dir,
                offline=offline,
                workspace=request.workspace,
                end_card=end_card,
                subtitles=subtitles.value if subtitles else None,
                fast=fast,
                ignore_exit=ignore_exit,
                sandbox=request,
                scenes=ranges,
                log=log,
            )
        else:
            result = build(
                spec,
                output,
                work_dir=work_dir,
                offline=offline,
                max_drift=max_drift,
                workspace=request.workspace,
                end_card=end_card,
                subtitles=subtitles.value if subtitles else None,
                draft=draft,
                fast=fast,
                ignore_exit=ignore_exit,
                sandbox=request,
                clean=clean,
                scenes=ranges,
                log=log,
            )
    err.print(
        f"{'cast' if cast else 'video'} {result.video_ms / 1000:.2f}s, "
        f"planned {result.expected_ms / 1000:.2f}s ({result.drift:+.1%})",
        highlight=False,
    )
    out.print(str(result.output), highlight=False, soft_wrap=True)
    return 0
