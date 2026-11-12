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
    """Parse and validate a spec; report every problem with its line number.

    Valid but redundant lines (defaults, a trailing `hold: auto`, ...) are reported as hints,
    likely authoring problems in Markdown docs as warnings (`lint: false` turns them off).
    """
    from rich.markup import escape

    from narratty.spec.compile import markdown_warnings
    from narratty.spec.hints import find_hints
    from narratty.spec.loader import Issue, parse_document, read_spec_text
    from narratty.ui.console import err, out

    document = parse_document(read_spec_text(spec), spec)
    loaded = document.spec
    check_voice(loaded.tts.provider, loaded.tts.voice)
    for hint in find_hints(*document):
        err.print(f"[yellow]hint:[/] {escape(hint.render(spec))}", highlight=False, soft_wrap=True)
    for warning in markdown_warnings(document, spec):
        where = Issue("", warning.what, warning.line, None, warning.file)
        err.print(f"[yellow]warning:[/] {escape(where.render(spec))}", highlight=False, soft_wrap=True)
    narrated = len(loaded.narrated_scenes)
    out.print(
        f"[green]ok[/] {spec}: {len(loaded.scenes)} scenes, {narrated} narrated, "
        f"voice {loaded.tts.provider}/{loaded.tts.voice}",
        highlight=False,
        soft_wrap=True,
    )
