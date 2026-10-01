"""Exit codes of the commands a recording runs, checked against their ``expect_exit``.

A hook installed with the prompt appends ``<status>\\t<command line>`` to a log for
every command line run at the shell prompt. After recording, each entry is tied to
the scene that typed that line, and the scenes' expectations are checked.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from narratty.errors import CommandError
from narratty.render.script import Ctrl, Press, Type, action_steps
from narratty.spec.model import ExpectExit, Run, Scene, Spec
from narratty.timeline import Pacing

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


@dataclass(frozen=True)
class Typed:
    """A line a scene types and submits, with the expectation of its ``run`` action."""

    scene_id: str
    line: str
    expect: ExpectExit | None = None


def typed_commands(spec: Spec) -> list[Typed]:
    """Every line the scenes type and submit with Enter, in order."""
    commands = []
    for scene in spec.scenes:
        line = ""
        for action in scene.actions:
            expect = action.expect_exit if isinstance(action, Run) else None
            for step in action_steps(action, Pacing(speed=1)):
                if isinstance(step, Type):
                    line += step.text
                elif isinstance(step, Press) and step.key == "Enter":
                    if line.strip():
                        commands.append(Typed(scene.id, line.strip(), expect))
                    line = ""
                elif isinstance(step, Ctrl):
                    line = ""
    return commands


def assign(
    spec: Spec, entries: list[Exit], commands: list[Typed] | None = None
) -> list[tuple[Typed | None, Exit]]:
    """Each entry with the typed line it came from.

    An entry belongs to the next typed line it equals or starts with (keys such as
    Tab may complete a line). Entries matching no typed line count toward the line of
    the entry before them; those before any match get ``None``.
    """
    commands = typed_commands(spec) if commands is None else commands
    pairs: list[tuple[Typed | None, Exit]] = []
    position, current = 0, None
    for entry in entries:
        for index in range(position, len(commands)):
            if entry.line == commands[index].line or entry.line.startswith(commands[index].line):
                position, current = index + 1, commands[index]
                break
        pairs.append((current, entry))
    return pairs


def problems(spec: Spec, entries: list[Exit], default: ExpectExit = "success") -> list[str]:
    """What contradicts the expectations, one message per scene or command.

    A ``run`` action's ``expect_exit`` wins over its scene's, which wins over ``default``.
    """
    commands = typed_commands(spec)
    pairs = assign(spec, entries, commands)
    found = []
    if default != "any":
        found += [
            _failed("before the first scene", e) for typed, e in pairs if typed is None and _failed_status(e)
        ]
    for typed in commands:
        if typed.expect is not None:
            found += _command_problems(typed, [e for t, e in pairs if t is typed])
    for scene in spec.scenes:
        scene_entries = [e for t, e in pairs if t is not None and t.scene_id == scene.id and t.expect is None]
        found += _scene_problems(scene, scene.expect_exit or default, scene_entries)
    return found


def _failed_status(entry: Exit) -> bool:
    return entry.status != 0 and entry.status not in INTERRUPTED


def _failed(where: str, entry: Exit) -> str:
    return f"{where}: `{entry.line}` exited with {entry.status}"


def _command_problems(typed: Typed, entries: list[Exit]) -> list[str]:
    where = f"scene {typed.scene_id!r}"
    if typed.expect == "success":
        return [_failed(where, e) for e in entries if _failed_status(e)]
    if typed.expect == "failure" and not any(_failed_status(e) for e in entries):
        outcome = "succeeded" if entries else "did not run at the shell prompt"
        return [f"{where}: `{typed.line}` is expected to fail but {outcome}"]
    return []


def _scene_problems(scene: Scene, expect: ExpectExit, entries: list[Exit]) -> list[str]:
    failed = [e for e in entries if _failed_status(e)]
    if expect == "success":
        return [_failed(f"scene {scene.id!r}", e) for e in failed]
    if expect == "failure" and not failed:
        if not entries:
            return [f"scene {scene.id!r} expects a command to fail but ran none at the shell prompt"]
        lines = ", ".join(f"`{e.line}`" for e in entries)
        return [f"scene {scene.id!r} expects a command to fail, but {lines} succeeded"]
    return []


def check(spec: Spec, log: Path, *, default: ExpectExit = "success", output: Path | None = None) -> None:
    """Raise :class:`CommandError` when the logged exit codes break an ``expect_exit``.

    ``default`` applies where neither the scene nor the ``run`` action sets one
    (``--ignore-exit`` makes it ``any``). ``output`` is the file already written,
    named in the hint for inspection.
    """
    if spec.terminal.shell in UNCHECKED_SHELLS or not log.is_file():
        return
    found = problems(spec, parse_log(log.read_text(encoding="utf-8", errors="replace")), default)
    if found:
        raise CommandError(
            "the recording may show failed commands:\n  " + "\n  ".join(found),
            hint="Fix the command, or set `expect_exit: failure` (must fail) or "
            "`expect_exit: any` (not checked) on the scene or its `run` action, "
            "or build with --ignore-exit." + (f" The output was written anyway: {output}" if output else ""),
        )
