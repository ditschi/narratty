"""``narratty tape``: print the generated VHS tape."""

from __future__ import annotations

from pathlib import Path

import typer

from narratty.cli.arguments import SpecArgument
from narratty.cli.options import EndCardOption, ImageOption, OfflineOption, RuntimeOption
from narratty.runtime import Runtime


def tape_command(
    spec: Path = SpecArgument,
    output: Path | None = typer.Option(None, "--output", "-o", help="Video path written into the tape."),
    end_card: bool | None = EndCardOption,
    offline: bool = OfflineOption,
    runtime: Runtime = RuntimeOption,
    image: str | None = ImageOption,
) -> None:
    """Print the VHS tape narratty would record (useful for debugging)."""
    from narratty.build import default_output, plan
    from narratty.container import delegate
    from narratty.end_card import container_flag
    from narratty.render.tape import generate_tape
    from narratty.ui.console import err

    extra = ["--output", str(output)] if output else []
    extra.append(container_flag(spec, end_card))
    code = delegate("tape", spec, runtime=runtime, image=image, extra_args=extra)
    if code is not None:
        raise typer.Exit(code)
    with err.status("synthesizing narration"):
        planned = plan(spec, offline=offline, end_card=end_card)
    video = (output or default_output(spec, ".silent.mp4")).resolve()
    typer.echo(generate_tape(planned.spec, planned.timeline, video), nl=False)
