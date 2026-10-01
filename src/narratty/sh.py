"""Commands narratty types into the demo's terminal for its own helpers.

The editor layout and the ``diff`` action are plain POSIX ``sh`` commands, so they run
wherever the demo shell runs, locally or in a project environment, without narratty
there. They are typed as ``sh -c '…'`` into bash, zsh, fish or sh, or as a quoted
argument at tmux's command prompt. So a script holds no single quote, no backslash
pair and no ``#``: :func:`word` spells every other character with printf escapes.

A helper that cannot work (a missing tool) prints ``narratty error: …``; the
recorders stop waiting and fail the build with that message (see :data:`ERROR`).
"""

from __future__ import annotations

import re
import string

ERROR = r"narratty error: (.+)"
"""What a failing helper prints; the typed command itself never matches it."""

_SAFE = frozenset(string.ascii_letters + string.digits + "_./:@+=,-")
_PLAIN = _SAFE | {" "}


def _printf(text: str, keep: frozenset[str]) -> str:
    spelled = "".join(
        char if char in keep else "%%" if char == "%" else "".join(f"\\{byte:03o}" for byte in char.encode())
        for char in text
    )
    return f'"$(printf "{spelled}")"'


def word(text: str) -> str:
    """``text`` as one sh word (double-quoted; printf escapes for unusual characters).

    Command substitution drops trailing newlines, so ``text`` should not end in one.
    """
    if all(char in _PLAIN for char in text):
        return f'"{text}"'
    return _printf(text, _SAFE)


def hidden_word(text: str) -> str:
    """``text`` as one sh word that does not show ``text`` itself where it is typed.

    For strings the recorder waits for on screen, such as a pane title.
    """
    return _printf(text, frozenset())


CLEAR = 'printf "\\033[H\\033[2J\\033[3J" >&2'
"""Clear the screen and the scrollback before a message the recorder waits for.

VHS's ``Wait+Screen`` reads the first rows of the terminal's buffer, not the visible
ones, so once a long typed command has scrolled the screen it would never see the
message. Without scrollback both are the same again.
"""


def fail(message: str) -> str:
    """Print ``narratty error: <message>`` to stderr (on a cleared screen) and exit 1."""
    return f'{{ {CLEAR}; printf "narratty %s: %s\\n" error {word(message)} >&2; exit 1; }}'


def need(tools: list[str], purpose: str, where: str) -> str:
    """Fail unless every one of ``tools`` is on ``PATH``."""
    return "; ".join(
        f"command -v {tool} >/dev/null 2>&1 || {fail(f'{purpose} needs {tool} {where}')}" for tool in tools
    )


def _check(script: str) -> str:
    if "'" in script or "#" in script or "\\\\" in script:
        raise ValueError(f"not safe to type: {script!r}")
    return script


def command(script: str) -> str:
    """``script`` as a command line for any interactive shell."""
    return f"sh -c '{_check(script)}'"


def tmux_arg(script: str) -> str:
    """``script`` as an argument at tmux's command prompt (``run-shell``, ``display-popup``).

    Single quotes keep tmux from expanding ``$`` and ``\\``; the script has no ``#``, so
    tmux's format expansion leaves it alone.
    """
    return f"'{_check(script)}'"


def error_in(text: str) -> str | None:
    """The message of the first ``narratty error:`` line in ``text``.

    A recorder's log may echo the pattern itself (VHS prints its ``Wait`` commands);
    that is not a message.
    """
    for match in re.finditer(ERROR, text):
        if not match.group(1).startswith("(.+)"):
            return match.group(1).strip()
    return None
