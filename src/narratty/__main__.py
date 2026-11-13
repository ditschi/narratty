"""Process entry point: run the Typer app and map errors to exit codes."""

from __future__ import annotations

import os
import signal
import sys
from types import FrameType

from narratty.cli.app import app
from narratty.errors import ExitCode, NarrattyError
from narratty.ui import console


def _terminated(_signum: int, _frame: FrameType | None) -> None:
    """SIGTERM unwinds like Ctrl+C, so workspaces and containers are cleaned up."""
    raise KeyboardInterrupt


def main() -> None:
    """Console-script entry point (``narratty``)."""
    signal.signal(signal.SIGTERM, _terminated)
    try:
        app()
    except NarrattyError as error:
        console.print_error(error)
        sys.exit(int(error.exit_code))
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as error:  # noqa: BLE001 - final CLI safety net
        if "--debug" in sys.argv or os.environ.get("NARRATTY_DEBUG"):
            raise
        console.print_error(
            NarrattyError(
                f"Unexpected internal error: {error}",
                hint="Re-run with --debug to see the full traceback.",
            )
        )
        sys.exit(int(ExitCode.GENERIC))


if __name__ == "__main__":
    main()
