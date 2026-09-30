"""``narratty build``: the full pipeline, from spec to narrated mp4 (or asciicast)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import typer

from narratty.cli.arguments import SpecArgument
from narratty.cli.options import (
    AllowDirtyOption,
    AllowHostOption,
    EndCardOption,
    ImageOption,
    KeepWorkspaceOption,
    NetworkMode,
    NetworkOption,
    OfflineOption,
    RuntimeOption,
    WorkspaceMode,
    WorkspaceModeOption,
    YesOption,
    check_hosts,
)
from narratty.runtime import Runtime


class OutputFormat(StrEnum):
    """Values of ``--format``."""

    MP4 = "mp4"
    CAST = "cast"


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
    workspace_mode: WorkspaceMode | None = WorkspaceModeOption,
    keep_workspace: bool = KeepWorkspaceOption,
    allow_dirty: bool = AllowDirtyOption,
    network: NetworkMode | None = NetworkOption,
    allow_host: list[str] | None = AllowHostOption,
    yes: bool = YesOption,
    end_card: bool | None = EndCardOption,
    offline: bool = OfflineOption,
    runtime: Runtime = RuntimeOption,
    image: str | None = ImageOption,
) -> None:
    """Build the narrated video (or asciicast)."""
    from narratty.build import WorkspaceOptions, build, build_cast, default_output
    from narratty.container import SandboxRequest, delegate
    from narratty.end_card import container_flag
    from narratty.ui.console import err, out

    cast = output_format is OutputFormat.CAST
    workspace = WorkspaceOptions(
        workspace_mode.value if workspace_mode else None, allow_dirty, keep_workspace
    )
    request = SandboxRequest(workspace, network.value if network else None, check_hosts(allow_host), yes)
    code = delegate(
        "build",
        spec,
        runtime=runtime,
        image=image,
        output=output or default_output(spec, f".{'html' if cast else 'mp4'}"),
        work_dir=work_dir,
        extra_args=[
            "--format",
            output_format.value,
            "--max-drift",
            str(max_drift),
            container_flag(spec, end_card),
        ],
        sandbox=request,
    )
    if code is not None:
        raise typer.Exit(code)

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
                workspace=workspace,
                end_card=end_card,
                log=log,
            )
        else:
            result = build(
                spec,
                output,
                work_dir=work_dir,
                offline=offline,
                max_drift=max_drift,
                workspace=workspace,
                end_card=end_card,
                log=log,
            )
    err.print(
        f"{'cast' if cast else 'video'} {result.video_ms / 1000:.2f}s, "
        f"planned {result.expected_ms / 1000:.2f}s ({result.drift:+.1%})",
        highlight=False,
    )
    out.print(str(result.output), highlight=False, soft_wrap=True)
