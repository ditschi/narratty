"""Console helpers: data goes to stdout, logs and errors go to stderr.

Honors ``NO_COLOR`` and non-TTY output automatically (rich handles this).
"""

from __future__ import annotations

from rich.console import Console

from narratty.errors import NarrattyError

out = Console()
err = Console(stderr=True)


def print_error(error: NarrattyError) -> None:
    """Render an error (message + optional next-step hint) to stderr."""
    err.print(f"[bold red]error:[/] {error.message}", highlight=False)
    if error.hint:
        err.print(f"[dim]hint:[/] {error.hint}", highlight=False)
