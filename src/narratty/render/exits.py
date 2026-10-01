"""Exit codes of the commands a recording runs, checked against each scene's ``expect_exit``.

A hook installed with the prompt appends ``<status>\\t<command line>`` to a log for
every command line run at the shell prompt. After recording, each entry is tied to
the scene that typed that line, and the scenes' expectations are checked.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from narratty.errors import CommandError
from narratty.render.script import Ctrl, Press, Type, action_steps
from narratty.spec.model import Scene, Spec

# 128 + SIGINT / SIGTSTP: the scene stopped the command itself (C-c, C-z).
INTERRUPTED = frozenset({130, 148})
UNCHECKED_SHELLS = frozenset({"sh"})


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
        for step in (step for action in scene.actions for step in action_steps(action, 1)):
            if isinstance(step, Type):
                line += step.text
            elif isinstance(step, Press) and step.key == "Enter":
                if line.strip():
                    commands.append((scene.id, line.strip()))
                line = ""
            elif isinstance(step, Ctrl):
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
