"""The ``diff`` action: what changed in the workspace since the recording started.

When a spec uses ``diff``, the tape runs ``python -m narratty.diff start`` while
recording is hidden. It records the workspace in a private git repository (the
workspace's own ``.git`` is not touched, ``.gitignore`` is honoured). ``show`` prints
the changes since then with delta, else bat, else git's own colours.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import termios
import tty
from collections.abc import Iterable, Sequence
from pathlib import Path

BASE_ENV = "NARRATTY_DIFF_BASE"
READY = "diff baseline ready"
NO_CHANGES = "No changes."
# Build output that is rarely in a demo project's .gitignore.
_EXCLUDE = "__pycache__/\n*.py[co]\n"
_IDENTITY = ["-c", "user.name=narratty", "-c", "user.email=narratty@localhost", "-c", "core.autocrlf=false"]
_HIDE_CURSOR = "\x1b[?25l"


def base_dir(root: Path) -> Path:
    """Where the baseline lives: ``$NARRATTY_DIFF_BASE`` (set by ``build``) or a temp dir."""
    if override := os.environ.get(BASE_ENV):
        return Path(override)
    digest = hashlib.sha256(str(root).encode()).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"narratty-diff-{digest}"


def _git(base: Path, root: Path, *args: str, capture: bool = False) -> str:
    result = subprocess.run(
        ["git", *_IDENTITY, f"--git-dir={base / 'git'}", f"--work-tree={root}", *args],
        cwd=root,
        check=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
    )
    return result.stdout if capture else ""


def _own_objects(root: Path) -> Path | None:
    """The object store of the repository ``root`` belongs to, if any."""
    try:
        git_dir = subprocess.run(
            ["git", "rev-parse", "--absolute-git-dir"], cwd=root, check=True, text=True, capture_output=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    objects = Path(git_dir) / "objects"
    return objects if objects.is_dir() else None


def start(root: Path) -> Path:
    """Record ``root`` as the baseline; returns the baseline directory."""
    base = base_dir(root)
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)
    (base / "root").write_text(str(root), encoding="utf-8")
    subprocess.run(["git", "init", "-q", "--bare", str(base / "git")], check=True)
    (base / "git" / "info").mkdir(exist_ok=True)
    exclude = _EXCLUDE
    if base.resolve().is_relative_to(root.resolve()):
        exclude += f"/{base.resolve().relative_to(root.resolve()).as_posix()}/\n"
    (base / "git" / "info" / "exclude").write_text(exclude, encoding="utf-8")
    if objects := _own_objects(root):
        # Reuse the repository's objects: committed files are not copied again.
        (base / "git" / "objects" / "info" / "alternates").write_text(f"{objects}\n", encoding="utf-8")
    _git(base, root, "add", "-A")
    _git(base, root, "commit", "-q", "--allow-empty", "--no-verify", "-m", "baseline")
    return base


def changes(root: Path, paths: Sequence[str] = ()) -> str:
    """The diff since the baseline, as plain text."""
    base = base_dir(root)
    root = Path((base / "root").read_text(encoding="utf-8"))
    _git(base, root, "add", "-A")
    return _git(base, root, "diff", "--cached", "--no-color", "--", *paths, capture=True)


def pretty(diff: str) -> str:
    """Colour ``diff`` with delta or bat when they are installed."""
    if shutil.which("delta"):
        command = ["delta", "--paging=never"]
    elif shutil.which("bat"):
        command = ["bat", "--paging=never", "--color=always", "--language=diff", "--style=plain"]
    else:
        return diff
    return subprocess.run(
        command, input=diff, encoding="utf-8", errors="replace", capture_output=True, check=True
    ).stdout


def wait_for_key() -> None:
    """Block until a key is pressed (the tape closes the popup with Enter)."""
    fd = sys.stdin.fileno()
    if not os.isatty(fd):
        sys.stdin.read(1)
        return
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        os.read(fd, 1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def main(argv: Iterable[str] | None = None) -> None:
    """Command-line entry point (run by the tape)."""
    parser = argparse.ArgumentParser(prog="python -m narratty.diff", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("start", help="Record the current directory as the baseline.")
    show = commands.add_parser("show", help="Print the changes since the baseline.")
    show.add_argument("paths", nargs="*", help="Hex-encoded paths to limit the diff to.")
    show.add_argument("--wait", action="store_true", help="Wait for Enter afterwards (in a popup).")
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = Path.cwd()
    if args.command == "start":
        start(root)
        print(f"narratty: {READY}", file=sys.stderr)
        return
    diff = changes(root, [bytes.fromhex(path).decode() for path in args.paths])
    sys.stdout.write(pretty(diff) if diff else NO_CHANGES + "\n")
    if args.wait:
        sys.stdout.write(_HIDE_CURSOR)
        sys.stdout.flush()
        wait_for_key()


if __name__ == "__main__":
    main()
