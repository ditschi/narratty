"""``narratty validate``: check a spec without rendering anything."""

from __future__ import annotations

from pathlib import Path

from narratty.cli.arguments import SpecArgument


def validate_command(spec: Path = SpecArgument) -> None:
    """Parse and validate a spec; report every problem with its line number."""
    from narratty.spec import load_spec
    from narratty.ui.console import out

    loaded = load_spec(spec)
    narrated = len(loaded.narrated_scenes)
    out.print(
        f"[green]ok[/] {spec}: {len(loaded.scenes)} scenes, {narrated} narrated, "
        f"voice {loaded.tts.provider}/{loaded.tts.voice}",
        highlight=False,
        soft_wrap=True,
    )
