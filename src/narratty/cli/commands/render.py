"""``narratty render``: record the silent video only."""

from __future__ import annotations

from pathlib import Path

import typer

from narratty.cli.arguments import SpecArgument
from narratty.cli.options import (
    AllowDirtyOption,
    AllowHostOption,
    EndCardOption,
    EnvImageOption,
    ImageOption,
    KeepEnvOption,
    KeepWorkspaceOption,
    NetworkMode,
    NetworkOption,
    NoEnvOption,
    OfflineOption,
    RuntimeOption,
    WorkspaceMode,
    WorkspaceModeOption,
    YesOption,
    sandbox_request,
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
    env_image: str | None = EnvImageOption,
    no_env: bool = NoEnvOption,
    keep_env: bool = KeepEnvOption,
    yes: bool = YesOption,
    end_card: bool | None = EndCardOption,
    offline: bool = OfflineOption,
    runtime: Runtime = RuntimeOption,
    image: str | None = ImageOption,
) -> None:
    """Synthesize the narration (for timing) and record the silent video with VHS."""
    from narratty.build import (
        default_output,
        environment_bridge,
        plan,
        render_silent,
        work_directory,
        workspace_for,
    )
    from narratty.container import delegate
    from narratty.end_card import container_flag
    from narratty.ui.console import err

    video = (output or default_output(spec, ".silent.mp4")).resolve()
    request = sandbox_request(
        workspace_mode, keep_workspace, allow_dirty, network, allow_host, yes, env_image, no_env, keep_env
    )
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
        workspace_for(planned, request.workspace, request) as ws,
        environment_bridge(planned, ws, request) as bridge,
    ):
        render_silent(planned, video, work, ws.path, bridge)
    err.print(f"[green]wrote[/] {video}", highlight=False, soft_wrap=True)
