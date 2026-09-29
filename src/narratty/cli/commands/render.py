"""``narratty render``: record the silent video only."""

from __future__ import annotations

from pathlib import Path

import typer

from narratty.cli.arguments import SpecArgument
from narratty.cli.options import ImageOption, OfflineOption, RuntimeOption
from narratty.runtime import Runtime


def render_command(
    spec: Path = SpecArgument,
    output: Path | None = typer.Option(None, "--output", "-o", help="Where to write the silent video."),
    offline: bool = OfflineOption,
    runtime: Runtime = RuntimeOption,
    image: str | None = ImageOption,
) -> None:
    """Synthesize the narration (for timing) and record the silent video with VHS."""
    from narratty.build import default_output, plan, render_silent, work_directory
    from narratty.container import delegate
    from narratty.ui.console import err

    video = (output or default_output(spec, ".silent.mp4")).resolve()
    code = delegate("render", spec, runtime=runtime, image=image, output=video)
    if code is not None:
        raise typer.Exit(code)
    with err.status("synthesizing narration"):
        planned = plan(spec, offline=offline)
    with err.status("recording with VHS"), work_directory(None) as work:
        render_silent(planned, video, work)
    err.print(f"[green]wrote[/] {video}", highlight=False, soft_wrap=True)
