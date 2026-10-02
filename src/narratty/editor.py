"""The editor layout (``terminal.layout: editor``): an explorer on top, a shell below.

While recording is hidden, the tape types :func:`start_command`. It checks for tmux,
yazi and ya, then starts a tmux server of its own (own socket, settings passed on the
command line) with yazi in the top pane and the demo's shell in the bottom one.
``reveal`` is run by that tmux server (``run-shell``) and tells yazi to select a path.

Everything is plain ``sh`` (see ``narratty.sh``), so the layout also starts in a
project environment that has those tools and no narratty.
"""

from __future__ import annotations

import secrets
import shlex

from narratty import sh
from narratty.render.shell_hooks import SHELL_ARGV

TERMINAL_HEIGHT = "30%"
ROOT_ENV, YAZI_ID_ENV = "NARRATTY_EDITOR_ROOT", "NARRATTY_YAZI_ID"
# Pane titles of the layout; the setup waits for the terminal's.
EXPLORER_TITLE, TERMINAL_TITLE = "Explorer", "Terminal"
TOOLS = ["tmux", "yazi", "ya"]
# A no-op word at the start of the start command. The shell it is typed into logs the
# command's exit code when tmux ends, which says nothing about the demo's commands.
MARK = "narratty-layout"

# tmux settings: quiet status line, titled panes, no delays. `-q`: options an older
# tmux does not know are skipped instead of shown as errors.
OPTIONS: list[list[str]] = [
    ["set", "-gq", "default-terminal", "tmux-256color"],
    ["set", "-asq", "terminal-features", ",xterm-256color:RGB"],
    ["set", "-gq", "default-shell", "/bin/sh"],  # runs the popups' scripts
    ["set", "-gq", "escape-time", "0"],
    ["set", "-gq", "base-index", "1"],
    ["setw", "-gq", "pane-base-index", "1"],
    ["set", "-gq", "mouse", "off"],
    ["set", "-gq", "status", "off"],
    ["set", "-gq", "pane-border-lines", "heavy"],
    ["set", "-gq", "pane-border-style", "fg=colour240"],
    ["set", "-gq", "pane-active-border-style", "fg=colour75"],
    ["set", "-gq", "pane-border-status", "top"],
    # Programs set pane titles (yazi does); the layout's own titles are pane options.
    ["set", "-gq", "pane-border-format", " #{?@title,#{@title},#{pane_current_command}} "],
    ["set", "-gq", "popup-border-lines", "rounded"],
    ["set", "-gq", "popup-border-style", "fg=colour75"],
]


def _join(commands: list[list[str]]) -> str:
    """tmux commands as sh words, separated by tmux's ``;``."""
    return ' ";" '.join(" ".join(sh.word(arg) for arg in command) for command in commands)


def start_command(
    shell: str,
    setup: str,
    *,
    terminal: str | None = None,
    where: str = "on this machine",
    yazi_id: int | None = None,
) -> str:
    """The command line that builds the layout.

    ``setup`` is typed into the terminal pane's shell first (prompt, exit-code hook).
    ``terminal`` is the pane's command (default: ``shell``); with a project environment
    whose workspace narratty shares, it opens the shell there while tmux and yazi stay
    here. ``where`` says where a missing tool is missing.
    """
    yazi_id = yazi_id or secrets.randbelow(2**48) + 1
    tmux = [
        ["start-server"],
        *OPTIONS,
        ["new-session", "-s", "narratty", f"yazi --client-id {yazi_id}"],
        ["split-window", "-v", "-l", TERMINAL_HEIGHT, terminal or shlex.join(SHELL_ARGV[shell])],
        ["send-keys", "-t", ":.2", "-l", setup],
        ["send-keys", "-t", ":.2", "Enter"],
    ]
    titles = [(":.1", EXPLORER_TITLE), (":.2", TERMINAL_TITLE)]
    script = "; ".join(
        [
            f": {MARK}",
            sh.need(TOOLS, "the editor layout", where),
            "unset TMUX",  # never nest in a caller's tmux
            f'export {ROOT_ENV}="$PWD" {YAZI_ID_ENV}={yazi_id}',
            # yazi opens text files with $EDITOR
            '[ -n "$EDITOR" ] || ! command -v micro >/dev/null 2>&1 || export EDITOR=micro',
            f"exec tmux -L narratty-{yazi_id} -f /dev/null {_join(tmux)}"
            + "".join(f' ";" set -p -t {pane} @title {sh.hidden_word(title)}' for pane, title in titles),
        ]
    )
    return sh.command(script)


def reveal_script(path: str) -> str:
    """Select ``path`` (relative to where the layout started) in yazi."""
    return f'ya emit-to "${YAZI_ID_ENV}" reveal "${ROOT_ENV}"/{sh.word(path)}'
