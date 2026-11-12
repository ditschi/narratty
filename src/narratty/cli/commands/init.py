"""``narratty init``: write a commented starter spec."""

from __future__ import annotations

from pathlib import Path

import typer

from narratty.errors import UsageError


def init_command(
    path: Path | None = typer.Argument(
        None,
        help="Where to write the spec (default: demo.narratty.yaml; with --markdown <doc>.narratty.yaml).",
        show_default=False,
    ),
    markdown: Path | None = typer.Option(
        None, "--markdown", "-m", help="Write a spec that makes the video from this Markdown doc."
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite an existing file."),
) -> None:
    """Write a commented starter spec you can edit."""
    import os

    from narratty import __version__
    from narratty.spec.loader import is_markdown
    from narratty.spec.template import render_markdown_template, render_template
    from narratty.ui.console import err

    if markdown is not None and not (markdown.is_file() and is_markdown(markdown)):
        raise UsageError(f"{markdown} is not a Markdown doc", hint="Pass an existing .md file to --markdown.")
    path = path or Path(f"{markdown.stem}.narratty.yaml" if markdown else "demo.narratty.yaml")
    if path.exists() and not force:
        raise UsageError(f"{path} already exists", hint="Pass --force to overwrite it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if markdown is None:
        text = render_template(__version__)
    else:
        doc = Path(os.path.relpath(markdown.resolve(), path.resolve().parent)).as_posix()
        text = render_markdown_template(__version__, doc)
    path.write_text(text, encoding="utf-8")
    err.print(f"wrote {path}", highlight=False)
