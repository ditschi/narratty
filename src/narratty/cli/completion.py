"""Shell-completion callbacks. They must stay cheap: no heavy imports, no I/O beyond listdir."""

from __future__ import annotations

import os
import re
from pathlib import Path

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


_SCENE_ID = re.compile(r"^\s*-\s+(?:\{\s*)?id:\s*[\"']?([a-z0-9][a-z0-9_-]*)")


def scene_ids(spec_path: Path) -> list[str]:
    """Scene ids of a spec, found by scanning its lines (no YAML parser, to stay quick)."""
    ids: list[str] = []
    in_scenes = False
    try:
        lines = spec_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        if line.startswith("scenes:"):
            in_scenes = True
        elif in_scenes and line[:1] not in (" ", "-", "#", ""):
            break
        elif in_scenes and (match := _SCENE_ID.match(line)):
            ids.append(match.group(1))
    return ids


def complete_scenes(ctx: typer.Context, incomplete: str) -> list[str]:
    """Complete scene ids for ``--scenes``, also after a ``,`` or ``:``."""
    # While an option is being completed, the spec is not parsed yet and sits in ctx.args.
    given = [
        Path(arg)
        for arg in (ctx.params.get("spec"), *ctx.args)
        if arg and str(arg).endswith((".yaml", ".yml"))
    ]
    spec = next((path for path in given if path.is_file()), None)
    if spec is None:
        found = sorted(Path().glob("*.narratty.y*ml"))
        spec = found[0] if len(found) == 1 else None
    if spec is None:
        return []
    head, sep, tail = incomplete.rpartition(",")
    head2, sep2, tail2 = tail.rpartition(":")
    prefix = f"{head}{sep}{head2}{sep2}"
    return [f"{prefix}{scene}" for scene in scene_ids(spec) if scene.startswith(tail2)]
