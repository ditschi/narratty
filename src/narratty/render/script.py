"""The recording script: what to type, press and wait for, in order.

Both recorders run it: ``tape`` turns it into a VHS tape, ``cast`` plays it in a
pseudo-terminal. Generating it once keeps the two in step.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from narratty.diff import READY as DIFF_READY
from narratty.end_card import CREDIT
from narratty.spec.model import (
    Action,
    CtrlSequence,
    Diff,
    Enter,
    Focus,
    Hold,
    Key,
    Reveal,
    Scene,
    Spec,
    TypeCommand,
    Wait,
)
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
LAYOUT_TIMEOUT_MS = 15_000
BASELINE_TIMEOUT_MS = 300_000
# Pane titles of the editor layout; the setup waits for the terminal's.
EXPLORER_TITLE, TERMINAL_TITLE = "Explorer", "Terminal"
PANES = {"explorer": ":.1", "terminal": ":.2"}


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def prompt_setup(shell: str, prompt: str) -> str:
    """Shell command that sets a fixed prompt and clears the screen."""
    if shell == "fish":
        return f"function fish_prompt; printf '%s' {_shell_quote(prompt)}; end; clear"
    return f"PS1={_shell_quote(prompt)}; clear"


def encode_path(path: str) -> str:
    """``path`` as hex, so it passes tmux and shell quoting unchanged."""
    return path.encode().hex()


def _module(python: str, module: str, *args: str) -> str:
    return " ".join([_shell_quote(python), "-m", f"narratty.{module}", *args])


def hidden(steps: list[Step], settle_ms: int = 300) -> list[Step]:
    """``steps`` unrecorded, then ``settle_ms`` for the screen to catch up."""
    return [Hide(), *steps, Sleep(settle_ms), Show()]


def tmux_command(command: str) -> list[Step]:
    """Run a tmux command through its prompt (``Ctrl+b :``), whatever pane has focus."""
    return [Ctrl("B"), Type(":", 1), Type(command, 1), Press("Enter", 1)]


def _tmux_string(text: str) -> str:
    """A double-quoted tmux argument (``text`` holds no ``"``, ``\\``, ``$`` or ``#``)."""
    return f'"{text}"'


@dataclass(frozen=True)
class Context:
    """What action steps depend on beyond the action: the layout and the helper interpreter."""

    editor: bool
    python: str


def diff_steps(action: Diff, context: Context) -> list[Step]:
    """Show the diff: a popup in the editor layout, else printed in the shell."""
    paths = [encode_path(path) for path in action.paths]
    if context.editor:
        show = _module(context.python, "diff", "show", "--wait", *paths)
        popup = f'display-popup -E -w 90% -h 85% -T " Diff " {_tmux_string(show)}'
        return hidden(tmux_command(popup), 1000)
    show = _module(context.python, "diff", "show", *paths)
    return hidden([Type(f"clear; {show}", 1), Press("Enter", 1)], 1000)


def close_popup() -> list[Step]:
    """Close the diff popup (it waits for Enter)."""
    return hidden([Press("Enter", 1)])


def editor_steps(action: Focus | Reveal, context: Context) -> list[Step]:
    """Steps for the editor layout's own actions."""
    if isinstance(action, Focus):
        return hidden(tmux_command(f"select-pane -t {PANES[action.focus]}"), 100)
    reveal = _module(context.python, "editor", "reveal", encode_path(action.reveal))
    return hidden(tmux_command(f"run-shell {_tmux_string(reveal)}"), 600)


def action_steps(action: Action, speed: int, context: Context | None = None) -> list[Step]:
    """Steps for one action (``hold: auto`` is placed by the caller)."""
    context = context or Context(editor=False, python=sys.executable)
    if isinstance(action, Diff):
        return diff_steps(action, context)
    if isinstance(action, Focus | Reveal):
        return editor_steps(action, context)
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


def _sends_keys(action: Action) -> bool:
    return not isinstance(action, Hold | Wait)


def _unhide(steps: list[Step]) -> list[Step]:
    """Inside a hidden scene, the steps without their own Hide/Show."""
    return [step for step in steps if not isinstance(step, Hide | Show)]


def scene_steps(spec: Spec, scene: Scene, timing: SceneTiming, *, python: str | None = None) -> list[Step]:
    """Steps for one scene, with its fill pause at ``hold: auto`` or at the end.

    In the editor layout a diff popup stays open until the next action that sends
    keys, or the end of the scene.
    """
    speed = typing_speed(spec, scene)
    context = Context(spec.terminal.layout == "editor", python or sys.executable)
    fill_at_hold = scene.narration_start == "with_actions"
    steps: list[Step] = [Mark(scene.id, scene.hidden)]
    if scene.hidden:
        steps.append(Hide())
    filled = popup = False
    for action in scene.actions:
        if isinstance(action, Hold) and action.hold == "auto" and fill_at_hold:
            if timing.fill_ms:
                steps.append(Sleep(timing.fill_ms))
            filled = True
            continue
        if popup and _sends_keys(action):
            steps += close_popup()
            popup = False
        steps += action_steps(action, speed, context)
        popup = popup or (context.editor and isinstance(action, Diff))
    if not filled and timing.fill_ms:
        steps.append(Sleep(timing.fill_ms))
    if popup:
        steps += close_popup()
    if scene.hidden:
        steps = [steps[0], steps[1], *_unhide(steps[2:])]
        # Clear what the hidden commands printed; hidden time is not recorded.
        if context.editor:
            steps += [*tmux_command("send-keys -t :.2 clear Enter"), Sleep(300), Show()]
        else:
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


def setup_steps(spec: Spec, python: str | None = None) -> list[Step]:
    """Unrecorded: record the diff baseline, set the prompt, clear, build the layout."""
    term = spec.terminal
    python = python or sys.executable
    steps: list[Step] = [Hide()]
    if spec.uses_diff:
        steps += [Type(_module(python, "diff", "start"), 1), Press("Enter", 1)]
        steps.append(WaitScreen(DIFF_READY, BASELINE_TIMEOUT_MS))
    # The pause is hidden, so it costs no time; it lets `clear` finish.
    steps += [Type(prompt_setup(term.shell, term.prompt), 1), Press("Enter", 1), Sleep(500)]
    if term.layout == "editor":
        start = _module(
            python, "editor", "start", "--shell", term.shell, "--prompt", _shell_quote(term.prompt)
        )
        steps += [
            Type(start, 1),
            Press("Enter", 1),
            WaitScreen(TERMINAL_TITLE, LAYOUT_TIMEOUT_MS),
            Sleep(1500),
        ]
    return [*steps, Show()]


def teardown_steps(spec: Spec) -> list[Step]:
    """Unrecorded: leave the editor layout, so the end card gets the whole terminal."""
    if spec.terminal.layout != "editor":
        return []
    return hidden(tmux_command("kill-server"), 500)


def build_script(spec: Spec, timeline: Timeline, *, python: str | None = None) -> list[Step]:
    """Every step of the recording, from prompt setup to the end card.

    ``python`` is the interpreter that draws the end card (default: the running one).
    """
    python = python or sys.executable
    steps = setup_steps(spec, python)
    if timeline.lead_in_ms:
        steps.append(Sleep(timeline.lead_in_ms))
    for scene in spec.scenes:
        steps += scene_steps(spec, scene, timeline.scene(scene.id), python=python)
    if timeline.tail_ms:
        steps.append(Sleep(timeline.tail_ms))
    if timeline.end_card_ms:
        steps += teardown_steps(spec) + end_card_steps(spec, timeline, python)
    return steps
