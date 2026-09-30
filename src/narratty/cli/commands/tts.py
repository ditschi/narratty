"""``narratty tts``: synthesize (or reuse from cache) every narration clip of a spec."""

from __future__ import annotations

from pathlib import Path

import typer

from narratty.cli.arguments import SpecArgument
from narratty.cli.options import ImageOption, OfflineOption, RuntimeOption
from narratty.runtime import Runtime


def tts_command(
    spec: Path = SpecArgument,
    offline: bool = OfflineOption,
    runtime: Runtime = RuntimeOption,
    image: str | None = ImageOption,
) -> None:
    """Synthesize the narration and print each clip's length."""
    from rich.table import Table

    from narratty.cache import AudioCache
    from narratty.container import delegate
    from narratty.paths import cache_dir, data_dir
    from narratty.spec import load_spec
    from narratty.tts.lexicon import load_lexicon
    from narratty.tts.registry import get_provider
    from narratty.tts.synth import synthesize_spec
    from narratty.ui.console import err, out

    code = delegate("tts", spec, runtime=runtime, image=image)
    if code is not None:
        raise typer.Exit(code)
    loaded = load_spec(spec)
    provider = get_provider(loaded.tts.provider, data_dir())
    with err.status(f"synthesizing with {provider.name}/{loaded.tts.voice}"):
        clips = synthesize_spec(
            loaded,
            provider,
            AudioCache(cache_dir()),
            download=not offline,
            lexicon=load_lexicon(spec, loaded.tts),
        )

    table = Table(show_header=True, header_style="bold")
    for column in ("scene", "length", "cache", "file"):
        table.add_column(column, overflow="fold" if column == "file" else "ellipsis")
    for clip in clips:
        table.add_row(
            clip.scene_id, f"{clip.duration_ms / 1000:.2f}s", "hit" if clip.cached else "new", str(clip.path)
        )
    out.print(table)
    total = sum(clip.duration_ms for clip in clips)
    err.print(f"{len(clips)} clips, {total / 1000:.2f}s of narration", highlight=False)
