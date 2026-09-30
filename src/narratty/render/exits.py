"""Exit codes of the commands a recording runs, checked against each scene's ``expect_exit``.

A hook installed with the prompt appends ``<status>\\t<command line>`` to a log for
every command line run at the shell prompt. After recording, each entry is tied to
the scene that typed that line, and the scenes' expectations are checked.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from narratty.errors import CommandError
from narratty.spec.model import CtrlSequence, Enter, Key, Scene, Spec, TypeCommand

# 128 + SIGINT / SIGTSTP: the scene stopped the command itself (C-c, C-z).
INTERRUPTED = frozenset({130, 148})
UNCHECKED_SHELLS = frozenset({"sh"})


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


@dataclass(frozen=True)
class Exit:
    """One command line and the exit code it left."""

    status: int
    line: str


def parse_log(text: str) -> list[Exit]:
    """Entries of an exit log; malformed lines are skipped."""
    entries = []
    for row in text.splitlines():
        status, sep, line = row.partition("\t")
        if sep and status.isdigit():
            entries.append(Exit(int(status), line.strip()))
    return entries


def typed_commands(spec: Spec) -> list[tuple[str, str]]:
    """``(scene id, line)`` for every line the scenes type and submit with Enter, in order."""
    commands = []
    for scene in spec.scenes:
        line = ""
        for action in scene.actions:
            if isinstance(action, TypeCommand):
                line += action.type_command
            elif isinstance(action, Enter) or (isinstance(action, Key) and action.key.split()[0] == "Enter"):
                if line.strip():
                    commands.append((scene.id, line.strip()))
                line = ""
            elif isinstance(action, CtrlSequence):
                line = ""
    return commands


def assign(spec: Spec, entries: list[Exit]) -> dict[str | None, list[Exit]]:
    """Entries by scene.

    An entry belongs to the next typed line it equals or starts with (keys such as
    Tab may complete a line). Entries matching no typed line count toward the scene
    of the entry before them; those before any match are under ``None``.
    """
    commands = typed_commands(spec)
    by_scene: dict[str | None, list[Exit]] = {}
    position, current = 0, None
    for entry in entries:
        for index in range(position, len(commands)):
            scene_id, typed = commands[index]
            if entry.line == typed or entry.line.startswith(typed):
                position, current = index + 1, scene_id
                break
        by_scene.setdefault(current, []).append(entry)
    return by_scene


def problems(spec: Spec, entries: list[Exit]) -> list[str]:
    """What contradicts the scenes' ``expect_exit``, one message per scene."""
    by_scene = assign(spec, entries)
    found = [_failed("before the first scene", e) for e in by_scene.get(None, []) if _failed_status(e)]
    for scene in spec.scenes:
        found += _scene_problems(scene, by_scene.get(scene.id, []))
    return found


def _failed_status(entry: Exit) -> bool:
    return entry.status != 0 and entry.status not in INTERRUPTED


def _failed(where: str, entry: Exit) -> str:
    return f"{where}: `{entry.line}` exited with {entry.status}"


def _scene_problems(scene: Scene, entries: list[Exit]) -> list[str]:
    failed = [e for e in entries if _failed_status(e)]
    if scene.expect_exit == "success":
        return [_failed(f"scene {scene.id!r}", e) for e in failed]
    if scene.expect_exit == "failure" and not failed:
        if not entries:
            return [f"scene {scene.id!r} expects a command to fail but ran none at the shell prompt"]
        lines = ", ".join(f"`{e.line}`" for e in entries)
        return [f"scene {scene.id!r} expects a command to fail, but {lines} succeeded"]
    return []


def check(spec: Spec, log: Path, *, output: Path | None = None) -> None:
    """Raise :class:`CommandError` when the logged exit codes break an ``expect_exit``.

    ``output`` is the file already written, named in the hint for inspection.
    """
    if spec.terminal.shell in UNCHECKED_SHELLS or not log.is_file():
        return
    found = problems(spec, parse_log(log.read_text(encoding="utf-8", errors="replace")))
    if found:
        raise CommandError(
            "the recording may show failed commands:\n  " + "\n  ".join(found),
            hint="Fix the command, or set `expect_exit: failure` (must fail) or "
            "`expect_exit: any` (not checked) on the scene."
            + (f" The output was written anyway: {output}" if output else ""),
        )
