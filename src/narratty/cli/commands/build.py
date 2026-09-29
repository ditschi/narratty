"""``narratty build``: the full pipeline, from spec to narrated mp4."""

from __future__ import annotations

from pathlib import Path

import typer

from narratty.cli.arguments import SpecArgument
from narratty.cli.options import ImageOption, OfflineOption, RuntimeOption
from narratty.runtime import Runtime


def build_command(
    spec: Path = SpecArgument,
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Where to write the video (default: next to the spec, as .mp4)."
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
    offline: bool = OfflineOption,
    runtime: Runtime = RuntimeOption,
    image: str | None = ImageOption,
) -> None:
    """Build the narrated video."""
    from narratty.build import build, default_output
    from narratty.container import delegate

    code = delegate(
        "build",
        spec,
        runtime=runtime,
        image=image,
        output=output or default_output(spec),
        work_dir=work_dir,
        extra_args=["--max-drift", str(max_drift)],
    )
    if code is not None:
        raise typer.Exit(code)

    from narratty.ui.console import err, out

    with err.status("building") as status:
        result = build(
            spec,
            output,
            work_dir=work_dir,
            offline=offline,
            max_drift=max_drift,
            log=lambda message: status.update(message),
        )
    err.print(
        f"video {result.video_ms / 1000:.2f}s, "
        f"planned {result.expected_ms / 1000:.2f}s ({result.drift:+.1%})",
        highlight=False,
    )
    out.print(str(result.output), highlight=False, soft_wrap=True)
