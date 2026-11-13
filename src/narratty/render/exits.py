"""Exit codes of the commands a recording runs, checked against their ``expect_exit``.

A hook installed with the prompt appends ``<status>\\t<command line>`` to a log for
every command line run at the shell prompt. After recording, each entry is tied to
the scene that typed that line, and the scenes' expectations are checked.

The lines narratty types itself (the ``clear`` that ends a hidden scene) are part of
the sequence too, so they cannot be mistaken for a scene's own command. Hidden scenes
may set secrets (``export TOKEN=...``): their lines are never shown in messages, and
:func:`check` rewrites the log so it keeps only the scene id and the command's number.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from narratty.errors import CommandError
from narratty.render.script import Context, Ctrl, Press, Type, action_steps
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
    hidden: int = 0
    """In a hidden scene: the command's number there (from 1); its line is not shown."""
    internal: bool = False
    """narratty's own line (the ``clear`` after a hidden scene), checked against nothing."""

    def shown(self, entry: Exit) -> str:
        """How messages quote ``entry``, which ran from this line."""
        if self.hidden:
            return f"hidden command {self.hidden}"
        return f"`{entry.line}`"


# What ends a hidden scene (see ``narratty.render.script``); the hook logs it too.
HIDDEN_SCENE_CLEAR = "clear"


def typed_commands(spec: Spec) -> list[Typed]:
    """Every line the scenes (and narratty, after a hidden scene) submit with Enter, in order."""
    commands = []
    # The prompt and shell shape the line a `run` with `show` or `max_lines` submits.
    context = Context(editor=False, prompt=spec.terminal.prompt, shell=spec.terminal.shell)
    for scene in spec.scenes:
        line = ""
        count = 0
        for action in scene.actions:
            expect = action.expect_exit if isinstance(action, Run) else None
            for step in action_steps(action, Pacing(speed=1), context):
                if isinstance(step, Type):
                    line += step.text
                elif isinstance(step, Press) and step.key == "Enter":
                    if line.strip():
                        count += 1
                        number = count if scene.hidden else 0
                        commands.append(Typed(scene.id, line.strip(), expect, hidden=number))
                    line = ""
                elif isinstance(step, Ctrl):
                    line = ""
        if scene.hidden:
            commands.append(Typed(scene.id, HIDDEN_SCENE_CLEAR, "any", internal=True))
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
            _failed("before the first scene", f"`{e.line}`", e)
            for typed, e in pairs
            if typed is None and _failed_status(e)
        ]
    for typed in commands:
        if typed.expect is not None and not typed.internal:
            found += _command_problems(typed, [e for t, e in pairs if t is typed])
    for scene in spec.scenes:
        scene_pairs = [
            (t, e) for t, e in pairs if t is not None and t.scene_id == scene.id and t.expect is None
        ]
        found += _scene_problems(scene, scene.expect_exit or default, scene_pairs)
    return found


def _failed_status(entry: Exit) -> bool:
    return entry.status != 0 and entry.status not in INTERRUPTED


def _failed(where: str, shown: str, entry: Exit) -> str:
    return f"{where}: {shown} exited with {entry.status}"


def _command_problems(typed: Typed, entries: list[Exit]) -> list[str]:
    where = f"scene {typed.scene_id!r}"
    if typed.expect == "success":
        return [_failed(where, typed.shown(e), e) for e in entries if _failed_status(e)]
    if typed.expect == "failure" and not any(_failed_status(e) for e in entries):
        outcome = "succeeded" if entries else "did not run at the shell prompt"
        shown = typed.shown(Exit(0, typed.line))
        return [f"{where}: {shown} is expected to fail but {outcome}"]
    return []


def _scene_problems(scene: Scene, expect: ExpectExit, pairs: list[tuple[Typed, Exit]]) -> list[str]:
    failed = [(t, e) for t, e in pairs if _failed_status(e)]
    if expect == "success":
        return [_failed(f"scene {scene.id!r}", t.shown(e), e) for t, e in failed]
    if expect == "failure" and not failed:
        if not pairs:
            return [f"scene {scene.id!r} expects a command to fail but ran none at the shell prompt"]
        lines = ", ".join(t.shown(e) for t, e in pairs)
        return [f"scene {scene.id!r} expects a command to fail, but {lines} succeeded"]
    return []


def redact(spec: Spec, log: Path) -> list[Exit]:
    """The log's entries; those of hidden scenes are rewritten in place without their line.

    A hidden entry becomes ``<status>\\t<hidden: <scene id> #<number>>``; malformed
    rows (parts of multi-line commands) are dropped.
    """
    text = log.read_text(encoding="utf-8", errors="replace")
    entries = parse_log(text)
    pairs = assign(spec, entries)
    hidden = any(typed is not None and typed.hidden for typed, _ in pairs)
    if not hidden and len(entries) == len(text.splitlines()):
        return entries
    rows = [
        f"{e.status}\t<hidden: {t.scene_id} #{t.hidden}>"
        if t is not None and t.hidden
        else f"{e.status}\t{e.line}"
        for t, e in pairs
    ]
    log.write_text("".join(f"{row}\n" for row in rows), encoding="utf-8")
    return entries


def check(spec: Spec, log: Path, *, default: ExpectExit = "success", output: Path | None = None) -> None:
    """Raise :class:`CommandError` when the logged exit codes break an ``expect_exit``.

    ``default`` applies where neither the scene nor the ``run`` action sets one
    (``--ignore-exit`` makes it ``any``). ``output`` is the file already written,
    named in the hint for inspection.
    """
    if not log.is_file():
        return
    entries = redact(spec, log)
    if spec.terminal.shell in UNCHECKED_SHELLS:
        return
    found = problems(spec, entries, default)
    if found:
        from narratty.paths import host_path

        output = host_path(output) if output else None
        raise CommandError(
            "the recording may show failed commands:\n  " + "\n  ".join(found),
            hint="Fix the command, or set `expect_exit: failure` (must fail) or "
            "`expect_exit: any` (not checked) on the scene or its `run` action, "
            "or build with --ignore-exit." + (f" The output was written anyway: {output}" if output else ""),
        )
