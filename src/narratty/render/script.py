"""The recording script: what to type, press and wait for, in order.

Both recorders run it: ``tape`` turns it into a VHS tape, ``cast`` plays it in a
pseudo-terminal. Generating it once keeps the two in step.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from narratty.end_card import CREDIT
from narratty.render.shell_hooks import exit_hook
from narratty.spec.model import Action, CtrlSequence, Enter, Hold, Key, Scene, Spec, TypeCommand, Wait
from narratty.timeline import SceneTiming, Timeline, typing_speed


@dataclass(frozen=True)
class Type:
    """Type ``text``, pausing ``speed_ms`` after each character."""

    text: str
    speed_ms: int


@dataclass(frozen=True)
class Press:
    """Press a named key (``Enter``, ``Down``, …) ``count`` times, ``speed_ms`` apart."""

    key: str
    speed_ms: int
    count: int | None = None


@dataclass(frozen=True)
class Ctrl:
    """Send Ctrl plus ``char``."""

    char: str


@dataclass(frozen=True)
class Sleep:
    """Pause."""

    ms: int


@dataclass(frozen=True)
class WaitScreen:
    """Block until the screen matches ``pattern``."""

    pattern: str
    timeout_ms: int


@dataclass(frozen=True)
class Hide:
    """Stop recording; what follows takes no time in the output."""


@dataclass(frozen=True)
class Show:
    """Resume recording."""


@dataclass(frozen=True)
class Mark:
    """Start of a section: a scene (``scene_id``) or the end card (``None``)."""

    scene_id: str | None
    hidden: bool = False


Step = Type | Press | Ctrl | Sleep | WaitScreen | Hide | Show | Mark

END_CARD_TIMEOUT_MS = 30_000


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def prompt_setup(shell: str, prompt: str, exit_log: Path | None = None) -> str:
    """Shell command that sets a fixed prompt and clears the screen.

    With ``exit_log``, it also installs the hook that logs exit codes there.
    """
    hook = exit_hook(shell, exit_log) if exit_log else None
    prefix = f"{hook}; " if hook else ""
    if shell == "fish":
        return f"{prefix}function fish_prompt; printf '%s' {_shell_quote(prompt)}; end; clear"
    return f"{prefix}PS1={_shell_quote(prompt)}; clear"


def action_steps(action: Action, speed: int) -> list[Step]:
    """Steps for one action (``hold: auto`` is placed by the caller)."""
    if isinstance(action, TypeCommand):
        return [Type(action.type_command, speed)]
    if isinstance(action, Enter):
        return [Press("Enter", speed)]
    if isinstance(action, Key):
        name, _, count = action.key.partition(" ")
        return [Press(name, speed, int(count) if count else None)]
    if isinstance(action, CtrlSequence):
        return [Ctrl(action.ctrl_sequence.removeprefix("C-").upper())]
    if isinstance(action, Wait):
        return [WaitScreen(action.wait.screen, action.wait.timeout_ms)]
    if isinstance(action, Hold) and action.hold != "auto":
        return [Sleep(action.hold)]
    return []


def scene_steps(spec: Spec, scene: Scene, timing: SceneTiming) -> list[Step]:
    """Steps for one scene, with its fill pause at ``hold: auto`` or at the end."""
    speed = typing_speed(spec, scene)
    fill_at_hold = scene.narration_start == "with_actions"
    steps: list[Step] = [Mark(scene.id, scene.hidden)]
    if scene.hidden:
        steps.append(Hide())
    filled = False
    for action in scene.actions:
        if isinstance(action, Hold) and action.hold == "auto" and fill_at_hold:
            if timing.fill_ms:
                steps.append(Sleep(timing.fill_ms))
            filled = True
            continue
        steps += action_steps(action, speed)
    if not filled and timing.fill_ms:
        steps.append(Sleep(timing.fill_ms))
    if scene.hidden:
        # Clear what the hidden commands printed; hidden time is not recorded.
        steps += [Type("clear", 1), Press("Enter", 1), Sleep(300), Show()]
    return steps


def end_card_steps(spec: Spec, timeline: Timeline, python: str) -> list[Step]:
    """Draw the end card while hidden, then keep it on screen for its duration."""
    command = f"{prompt_setup(spec.terminal.shell, '')}; {_shell_quote(python)} -m narratty.end_card"
    if not spec.end_card.qr:
        command += " --no-qr"
    return [
        Mark(None),
        Hide(),
        Type(command, 1),
        Press("Enter", 1),
        WaitScreen(CREDIT, END_CARD_TIMEOUT_MS),
        Show(),
        Sleep(timeline.end_card_ms),
    ]


def setup_steps(spec: Spec, exit_log: Path | None = None) -> list[Step]:
    """Set the prompt (and the exit-code hook) and clear the screen, unrecorded."""
    term = spec.terminal
    # The pause is hidden, so it costs no time; it lets `clear` finish.
    setup = prompt_setup(term.shell, term.prompt, exit_log)
    return [Hide(), Type(setup, 1), Press("Enter", 1), Sleep(500), Show()]


def build_script(
    spec: Spec, timeline: Timeline, *, python: str | None = None, exit_log: Path | None = None
) -> list[Step]:
    """Every step of the recording, from prompt setup to the end card.

    ``python`` is the interpreter that draws the end card (default: the running one);
    ``exit_log`` receives the commands' exit codes (see ``narratty.render.exits``).
    """
    steps = setup_steps(spec, exit_log)
    if timeline.lead_in_ms:
        steps.append(Sleep(timeline.lead_in_ms))
    for scene in spec.scenes:
        steps += scene_steps(spec, scene, timeline.scene(scene.id))
    if timeline.tail_ms:
        steps.append(Sleep(timeline.tail_ms))
    if timeline.end_card_ms:
        steps += end_card_steps(spec, timeline, python or sys.executable)
    return steps
