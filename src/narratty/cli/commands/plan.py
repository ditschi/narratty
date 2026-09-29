"""``narratty plan``: print the timeline without rendering."""

from __future__ import annotations

from pathlib import Path

import typer

from narratty.cli.arguments import SpecArgument
from narratty.cli.options import ImageOption, OfflineOption, RuntimeOption
from narratty.runtime import Runtime


def _seconds(ms: int) -> str:
    return f"{ms / 1000:.2f}s"


def plan_command(
    spec: Path = SpecArgument,
    offline: bool = OfflineOption,
    runtime: Runtime = RuntimeOption,
    image: str | None = ImageOption,
) -> None:
    """Show when each scene starts, how long it lasts and the total video length."""
    from rich.table import Table

    from narratty.build import plan
    from narratty.container import delegate
    from narratty.ui.console import err, out

    code = delegate("plan", spec, runtime=runtime, image=image)
    if code is not None:
        raise typer.Exit(code)
    with err.status("synthesizing narration"):
        planned = plan(spec, offline=offline)
    table = Table(show_header=True, header_style="bold")
    for column in ("scene", "start", "actions", "narration", "length"):
        table.add_column(column, justify="left" if column == "scene" else "right")
    for timing in planned.timeline.scenes:
        if timing.hidden:
            table.add_row(f"{timing.scene_id} [dim](hidden)[/]", "", "", "", "")
            continue
        narration = _seconds(timing.audio_ms) if timing.audio_ms else ""
        table.add_row(
            timing.scene_id,
            _seconds(timing.start_ms),
            _seconds(timing.action_ms),
            narration,
            _seconds(timing.length_ms),
        )
    out.print(table)
    out.print(f"total: {_seconds(planned.timeline.total_ms)}", highlight=False)
