"""Shell code that logs the exit code of every command line run at the prompt.

Each entry is ``<status>\\t<command line>``; ``narratty.render.exits`` checks them.
"""

from __future__ import annotations

from pathlib import Path

# How narratty starts each shell: no user configuration, no history.
SHELL_ARGV = {
    "bash": ["bash", "--noprofile", "--norc", "+o", "history"],
    "zsh": ["zsh", "--no-rcs", "--no-globalrcs"],
    "fish": ["fish", "--no-config", "--private"],
    "sh": ["sh"],
}


def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _fish_quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def exit_hook(shell: str, log: Path) -> str | None:
    """Shell code that logs the exit code of every command line, or None for ``sh``."""
    if shell == "bash":
        # bash has no preexec. From 4.0, Enter first copies the line; bash 3.2 (macOS)
        # lacks READLINE_LINE, so it turns history on (VHS turns it off) and reads it.
        return (
            "_narratty_line=; _narratty_last=; "
            "if ((BASH_VERSINFO[0] >= 4)); then "
            "bind -x '\"\\C-x\\C-n\": _narratty_line=$READLINE_LINE'; "
            'bind \'"\\C-m": "\\C-x\\C-n\\C-j"\'; '
            "else set -o history; fi; "
            "_narratty_exit() { local s=$? h re='^ *[0-9]+[*]? +(.*)$'; "
            "if ((BASH_VERSINFO[0] < 4)); then h=$(HISTTIMEFORMAT= builtin history 1); "
            '[[ $h != "$_narratty_last" && $h =~ $re ]] && _narratty_line=${BASH_REMATCH[1]}; '
            "_narratty_last=$h; fi; "
            "[[ $_narratty_line = *[![:space:]]* ]] && "
            f'printf \'%s\\t%s\\n\' "$s" "$_narratty_line" >>{_sh_quote(str(log))}; '
            "_narratty_line=; return $s; }; "
            "PROMPT_COMMAND=_narratty_exit"
        )
    if shell == "zsh":
        return (
            "_narratty_line=; "
            "_narratty_pre() { _narratty_line=$1; }; "
            "_narratty_exit() { local s=$?; "
            "[[ $_narratty_line = *[^[:space:]]* ]] && "
            f"print -r -- \"$s\"$'\\t'\"${{_narratty_line//$'\\n'/ }}\" >>{_sh_quote(str(log))}; "
            "_narratty_line=; }; "
            "preexec_functions+=(_narratty_pre); precmd_functions+=(_narratty_exit)"
        )
    if shell == "fish":
        return (
            "function _narratty_exit --on-event fish_postexec; set -l s $status; "
            "string match -qr '\\S' -- $argv[1]; "
            "and printf '%s\\t%s\\n' $s (string join ' ' -- (string split \\n -- $argv[1])) "
            f">>{_fish_quote(str(log))}; "
            "end"
        )
    return None
