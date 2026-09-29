"""Options shared by several subcommands."""

from __future__ import annotations

import typer

from narratty.runtime import Runtime

RuntimeOption = typer.Option(
    Runtime.AUTO,
    "--runtime",
    "-r",
    envvar="NARRATTY_RUNTIME",
    case_sensitive=False,
    help="Where to run: auto (container if available), native, docker or podman.",
)
