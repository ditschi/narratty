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

OfflineOption = typer.Option(
    False, "--offline", envvar="NARRATTY_OFFLINE", help="Fail instead of downloading a missing voice."
)

ImageOption = typer.Option(
    None,
    "--image",
    envvar="NARRATTY_IMAGE",
    help="Container image to use (default: ghcr.io/ditschi/narratty matching this version).",
)
