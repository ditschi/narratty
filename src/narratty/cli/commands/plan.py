"""``narratty plan``: print the timeline without rendering."""

from __future__ import annotations

from pathlib import Path

import typer

from narratty.cli.arguments import SpecArgument
from narratty.cli.options import EndCardOption, ImageOption, OfflineOption, RuntimeOption
from narratty.runtime import Runtime


def _seconds(ms: int) -> str:
    return f"{ms / 1000:.2f}s"


def plan_command(
    spec: Path = SpecArgument,
    end_card: bool | None = EndCardOption,
    draft: bool = typer.Option(False, "--draft", help="Estimate narration lengths instead of running TTS."),
    offline: bool = OfflineOption,
    runtime: Runtime = RuntimeOption,
    image: str | None = ImageOption,
) -> None:
    """Show when each scene starts, how long it lasts and the total video length."""
    from rich.table import Table

    from narratty.build import plan
    from narratty.container import delegate
    from narratty.end_card import container_flag
    from narratty.ui.console import err, out

    extra = [container_flag(spec, end_card), *(["--draft"] if draft else [])]
    code = delegate("plan", spec, runtime=runtime, image=image, extra_args=extra)
    if code is not None:
        raise typer.Exit(code)
    with err.status("estimating narration" if draft else "synthesizing narration"):
        planned = plan(spec, offline=offline, end_card=end_card, draft=draft)
    table = Table(show_header=True, header_style="bold")
    for column in ("scene", "start", "actions", "narration", "length"):
        table.add_column(column, justify="left" if column == "scene" else "right")
    for timing in planned.timeline.scenes:
        if timing.hidden:
            table.add_row(f"{timing.scene_id} [dim](hidden)[/]", "", "", "", "")
            continue
        narration = _seconds(timing.audio_ms) if timing.audio_ms else ""
        name = timing.scene_id + (f" [dim](×{timing.timelapse:g}, plus waits)[/]" if timing.timelapse else "")
        table.add_row(
            name,
            _seconds(timing.start_ms),
            _seconds(timing.action_ms),
            narration,
            _seconds(timing.length_ms),
        )
    if planned.timeline.end_card_ms:
        table.add_row("[dim]end card[/]", "", "", "", _seconds(planned.timeline.end_card_ms))
    out.print(table)
    out.print(
        f"total: {_seconds(planned.timeline.total_ms)}" + (" (estimated)" if draft else ""), highlight=False
    )
