"""Shell-completion callbacks. They must stay cheap: no heavy imports, no I/O beyond listdir."""

from __future__ import annotations

import os

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
