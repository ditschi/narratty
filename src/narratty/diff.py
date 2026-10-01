"""The ``diff`` action: what changed in the workspace since the recording started.

When a spec uses ``diff``, the tape types :func:`start_command` while recording is
hidden. It records the shell's working directory in a private git repository (the
workspace's own ``.git`` is not touched, ``.gitignore`` is honoured). :func:`show_script`
prints the changes since then with delta, else bat, else plain.

Both are plain ``sh`` and need only git (see ``narratty.sh``), so they also run in a
project environment without narratty.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePosixPath

from narratty import sh

READY = "diff baseline ready"
NO_CHANGES = "No changes."
# Build output that is rarely in a demo project's .gitignore.
_EXCLUDE = ["__pycache__/", "*.py[co]"]
_GIT = "git -c user.name=narratty -c user.email=narratty@localhost -c core.autocrlf=false"


def _git(work_tree: str) -> str:
    """A shell function ``g`` that runs git on the baseline in ``$b``."""
    return f'g() {{ {_GIT} --git-dir="$b/git" --work-tree={work_tree} "$@"; }}'


def start_command(base: str, where: str = "on this machine") -> str:
    """Record the working directory as the baseline in ``base`` (replaced if it exists)."""
    ready, rest = READY.rsplit(" ", 1)
    exclude = [*_EXCLUDE, f"{PurePosixPath(base).name}/"]  # in case it lies in the workspace
    steps = " && ".join(
        [
            f"b={sh.word(base)}",
            'rm -rf "$b"',
            'mkdir -p "$b"',
            'pwd > "$b/root"',
            'git init -q --bare "$b/git"',
            'mkdir -p "$b/git/info"',
            f'printf "%s\\n" {" ".join(sh.word(line) for line in exclude)} > "$b/git/info/exclude"',
            # Reuse the repository's objects: committed files are not copied again.
            '{ o=$(git rev-parse --absolute-git-dir 2>/dev/null) && [ -d "$o/objects" ]'
            ' && echo "$o/objects" > "$b/git/objects/info/alternates"; true; }',
            _git('"$PWD"'),
            "g add -A",
            "g commit -q --allow-empty --no-verify -m baseline",
            sh.CLEAR,
            f'printf "narratty: {ready} %s\\n" {rest} >&2',
        ]
    )
    failed = sh.fail("recording the diff baseline failed")
    script = f"{sh.need(['git'], 'the diff action', where)}; {{ {steps}; }} || {failed}"
    return sh.command(script)


def show_script(base: str, paths: Sequence[str] = (), *, wait: bool = False) -> str:
    """Print the changes since the baseline in ``base``, limited to ``paths``.

    ``wait``: hide the cursor and wait for Enter afterwards (in a popup).
    """
    limit = " ".join(sh.word(path) for path in paths)
    pretty = (
        'if [ -z "$d" ]; then echo ' + sh.word(NO_CHANGES) + "; "
        'elif command -v delta >/dev/null 2>&1; then printf "%s\\n" "$d" | delta --paging=never; '
        'elif command -v bat >/dev/null 2>&1; then printf "%s\\n" "$d"'
        " | bat --paging=never --color=always --language=diff --style=plain; "
        'else printf "%s\\n" "$d"; fi'
    )
    script = (
        f'b={sh.word(base)}; r=$(cat "$b/root") && cd "$r" && {_git('"$r"')}'
        f" && g add -A && d=$(g diff --cached --no-color -- {limit}) && {{ {pretty}; }}"
    )
    if wait:
        script += '; printf "\\033[?25l"; read -r _'
    return script
