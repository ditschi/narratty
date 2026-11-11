"""``narratty compile``: write the spec with its Markdown entries expanded."""

from __future__ import annotations

from pathlib import Path

import typer

from narratty.cli.arguments import SpecArgument


def compile_command(
    spec: Path = SpecArgument,
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Write the YAML to this file instead of stdout.", show_default=False
    ),
) -> None:
    """Print the spec with every `markdown` entry replaced by its scenes.

    The result is a plain spec: a way out of Markdown input, or a frozen copy to build from.
    """
    import sys

    from narratty.spec.compile import compile_spec
    from narratty.ui.console import err

    text = compile_spec(spec)
    if output is None:
        sys.stdout.write(text)
        return
    output.write_text(text, encoding="utf-8")
    err.print(f"wrote {output}", highlight=False)
