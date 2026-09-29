"""``narratty validate``: check a spec without rendering anything."""

from __future__ import annotations

from pathlib import Path

from narratty.cli.arguments import SpecArgument


def check_voice(provider_name: str, voice: str) -> None:
    """Fail when the voice is neither curated nor installed locally (no download, no model load)."""
    from narratty.paths import data_dir
    from narratty.tts.base import unknown_voice_error
    from narratty.tts.registry import get_provider

    provider = get_provider(provider_name, data_dir())
    if voice not in {info.id for info in provider.voices()}:
        raise unknown_voice_error(provider, voice)


def validate_command(spec: Path = SpecArgument) -> None:
    """Parse and validate a spec; report every problem with its line number."""
    from narratty.spec import load_spec
    from narratty.ui.console import out

    loaded = load_spec(spec)
    check_voice(loaded.tts.provider, loaded.tts.voice)
    narrated = len(loaded.narrated_scenes)
    out.print(
        f"[green]ok[/] {spec}: {len(loaded.scenes)} scenes, {narrated} narrated, "
        f"voice {loaded.tts.provider}/{loaded.tts.voice}",
        highlight=False,
        soft_wrap=True,
    )
