"""The editor layout (``terminal.layout: editor``): an explorer on top, a shell below.

The tape runs ``python -m narratty.editor start`` while recording is hidden. It
replaces itself with a tmux server of its own (own socket and config), with yazi in
the top pane and the demo's shell in the bottom one. ``reveal`` is run by that tmux
server (``run-shell``) and tells yazi to select a path.
"""

from __future__ import annotations

import argparse
import os
import secrets
import shlex
import shutil
import subprocess
from collections.abc import Iterable
from importlib.resources import as_file, files
from pathlib import Path

from narratty.render.cast import SHELL_ARGV
from narratty.render.script import EXPLORER_TITLE, TERMINAL_TITLE, prompt_setup

TERMINAL_HEIGHT = "30%"
ROOT_ENV, YAZI_ID_ENV = "NARRATTY_EDITOR_ROOT", "NARRATTY_YAZI_ID"


def decode_path(value: str) -> str:
    """A path the tape passed hex-encoded (see ``narratty.render.script.encode_path``)."""
    return bytes.fromhex(value).decode()


def tmux_argv(shell: str, prompt: str, config: Path, yazi_id: int, socket: str) -> list[str]:
    """The tmux command line that builds the layout."""
    explorer = shlex.join(["yazi", "--client-id", str(yazi_id)])
    terminal = shlex.join(SHELL_ARGV[shell])
    return [
        "tmux", "-L", socket, "-f", str(config),
        "new-session", "-s", "narratty", explorer, ";",
        "split-window", "-v", "-l", TERMINAL_HEIGHT, terminal, ";",
        "send-keys", "-t", ":.2", "-l", prompt_setup(shell, prompt), ";",
        "send-keys", "-t", ":.2", "Enter", ";",
        "set", "-p", "-t", ":.1", "@title", EXPLORER_TITLE, ";",
        "set", "-p", "-t", ":.2", "@title", TERMINAL_TITLE,
    ]  # fmt: skip


def start(shell: str, prompt: str) -> None:
    """Replace this process with the layout's tmux server."""
    yazi_id = secrets.randbelow(2**48) + 1
    env = {k: v for k, v in os.environ.items() if k != "TMUX"}  # never nest in a caller's tmux
    env[ROOT_ENV] = os.getcwd()
    env[YAZI_ID_ENV] = str(yazi_id)
    if "EDITOR" not in env and shutil.which("micro"):
        env["EDITOR"] = "micro"  # yazi opens text files with it
    with as_file(files("narratty").joinpath("data/editor.tmux.conf")) as config:
        argv = tmux_argv(shell, prompt, config, yazi_id, f"narratty-{os.getpid()}")
        os.execvpe(argv[0], argv, env)


def reveal(path: str) -> None:
    """Select ``path`` (relative to where the layout started) in yazi."""
    target = Path(os.environ.get(ROOT_ENV, os.getcwd()), path)
    subprocess.run(["ya", "emit-to", os.environ[YAZI_ID_ENV], "reveal", str(target)], check=True)


def main(argv: Iterable[str] | None = None) -> None:
    """Command-line entry point (run by the tape)."""
    parser = argparse.ArgumentParser(prog="python -m narratty.editor", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    start_parser = commands.add_parser("start", help="Build the layout.")
    start_parser.add_argument("--shell", choices=sorted(SHELL_ARGV), default="bash")
    start_parser.add_argument("--prompt", default="$ ")
    reveal_parser = commands.add_parser("reveal", help="Select a path in the explorer.")
    reveal_parser.add_argument("path", help="Hex-encoded path.")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "start":
        start(args.shell, args.prompt)
    else:
        reveal(decode_path(args.path))


if __name__ == "__main__":
    main()
