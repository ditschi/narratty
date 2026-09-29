"""``narratty init``: write a commented starter spec."""

from __future__ import annotations

from pathlib import Path

import typer

from narratty.errors import UsageError


def init_command(
    path: Path = typer.Argument(Path("demo.narratty.yaml"), help="Where to write the new spec."),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite an existing file."),
) -> None:
    """Write a commented starter spec you can edit."""
    from narratty.spec.template import TEMPLATE
    from narratty.ui.console import err

    if path.exists() and not force:
        raise UsageError(f"{path} already exists", hint="Pass --force to overwrite it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE, encoding="utf-8")
    err.print(f"wrote {path}", highlight=False)
