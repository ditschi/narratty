"""Typer application: wires global options and subcommands.

Kept thin on purpose. Each command lives in its own module under
``narratty.cli.commands`` and imports heavy dependencies lazily, so ``--help``
and shell completion stay fast.
"""

from __future__ import annotations

import os

import typer

from narratty import __version__
from narratty.cli.commands.doctor import doctor_command
from narratty.cli.commands.init import init_command
from narratty.cli.commands.schema import schema_command
from narratty.cli.commands.validate import validate_command

app = typer.Typer(
    name="narratty",
    help="Turn a YAML script into a narrated terminal video.",
    no_args_is_help=True,
    add_completion=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"narratty {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Show Python stack traces for unexpected internal errors.",
    ),
) -> None:
    """Turn a YAML script into a narrated terminal video."""
    _ = version
    if debug:
        os.environ["NARRATTY_DEBUG"] = "1"


app.command("init")(init_command)
app.command("validate")(validate_command)
app.command("schema")(schema_command)
app.command("doctor")(doctor_command)
