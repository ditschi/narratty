"""``narratty render``: record the silent video only."""

from __future__ import annotations

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


def render_command(
    spec: Path = SpecArgument,
    output: Path | None = typer.Option(None, "--output", "-o", help="Where to write the silent video."),
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
    """Synthesize the narration (for timing) and record the silent video with VHS."""
    from narratty.build import (
        WorkspaceOptions,
        default_output,
        plan,
        render_silent,
        work_directory,
        workspace_for,
    )
    from narratty.container import SandboxRequest, delegate
    from narratty.end_card import container_flag
    from narratty.ui.console import err

    video = (output or default_output(spec, ".silent.mp4")).resolve()
    workspace = WorkspaceOptions(
        workspace_mode.value if workspace_mode else None, allow_dirty, keep_workspace
    )
    request = SandboxRequest(workspace, network.value if network else None, check_hosts(allow_host), yes)
    code = delegate(
        "render",
        spec,
        runtime=runtime,
        image=image,
        output=video,
        extra_args=[container_flag(spec, end_card)],
        sandbox=request,
    )
    if code is not None:
        raise typer.Exit(code)
    with err.status("synthesizing narration"):
        planned = plan(spec, offline=offline, end_card=end_card)
    with (
        err.status("recording with VHS"),
        work_directory(None) as work,
        workspace_for(planned, workspace) as ws,
    ):
        render_silent(planned, video, work, ws.path)
    err.print(f"[green]wrote[/] {video}", highlight=False, soft_wrap=True)
