"""Arguments shared by several subcommands."""

from __future__ import annotations

import typer

from narratty.cli.completion import complete_spec_path

SpecArgument = typer.Argument(
    ...,
    help="Path to a .narratty.yaml spec, or a Markdown doc to build on its own.",
    autocompletion=complete_spec_path,
    show_default=False,
)
