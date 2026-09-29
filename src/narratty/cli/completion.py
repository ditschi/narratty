"""Shell-completion callbacks. They must stay cheap: no heavy imports, no I/O beyond listdir."""

from __future__ import annotations

import os

import typer

SPEC_SUFFIXES = (".narratty.yaml", ".narratty.yml")


def complete_spec_path(incomplete: str) -> list[str]:
    """Complete spec files (``*.narratty.yaml``) and directories to descend into."""
    directory, _, prefix = incomplete.rpartition("/")
    base = directory or "."
    if incomplete.startswith("/") and not directory:
        base = "/"
    try:
        entries = sorted(os.scandir(base), key=lambda entry: entry.name)
    except OSError:
        return []
    head = f"{directory}/" if directory or incomplete.startswith("/") else ""
    matches: list[str] = []
    for entry in entries:
        name = entry.name
        if not name.startswith(prefix) or (name.startswith(".") and not prefix.startswith(".")):
            continue
        try:
            is_dir = entry.is_dir()
        except OSError:  # pragma: no cover - broken symlink race
            continue
        if is_dir:
            matches.append(f"{head}{name}/")
        elif name.endswith(SPEC_SUFFIXES):
            matches.append(f"{head}{name}")
    return matches


def complete_provider(incomplete: str) -> list[str]:
    """Complete TTS provider names."""
    from narratty.tts.catalog import PROVIDERS

    return [name for name in PROVIDERS if name.startswith(incomplete)]


def complete_voice(ctx: typer.Context, incomplete: str) -> list[str]:
    """Complete curated voice ids, of the ``--provider`` given on the command line if any."""
    from narratty.tts.catalog import voice_ids

    provider = ctx.params.get("provider")
    return [voice for voice in voice_ids(provider) if voice.startswith(incomplete)]
