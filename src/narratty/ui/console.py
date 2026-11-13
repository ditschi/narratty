"""Console helpers: data goes to stdout, logs and errors go to stderr.

Honors ``NO_COLOR`` and non-TTY output automatically (rich handles this).
"""

from __future__ import annotations

import os

from rich.console import Console
from rich.markup import escape

from narratty.errors import NarrattyError
from narratty.paths import HOST_SPEC_ENV

out = Console()
err = Console(stderr=True)


def print_error(error: NarrattyError) -> None:
    """Render an error (message + optional next-step hint) to stderr."""
    message = error.message
    container, sep, host = os.environ.get(HOST_SPEC_ENV, "").partition("=")
    if sep and container:  # in the container: name the spec as the host knows it
        message = message.replace(container, host)
    # emoji=False: image tags and paths such as `img:x:` are not emoji codes.
    err.print(f"[bold red]error:[/] {escape(message)}", highlight=False, soft_wrap=True, emoji=False)
    if error.hint:
        err.print(f"[dim]hint:[/] {escape(error.hint)}", highlight=False, soft_wrap=True, emoji=False)
