"""The recording script: what to type, press and wait for, in order.

Both recorders run it: ``tape`` turns it into a VHS tape, ``cast`` plays it in a
pseudo-terminal. Generating it once keeps the two in step.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from narratty.diff import READY as DIFF_READY
from narratty.end_card import CREDIT
from narratty.render.shell_hooks import exit_hook
from narratty.spec.model import (
    Action,
    CtrlSequence,
    Diff,
    Enter,
    Focus,
    Hold,
    Key,
    Reveal,
    Run,
    Scene,
    ShowOverlay,
    Spec,
    TypeCommand,
    Wait,
)
from narratty.timeline import Pacing, SceneTiming, Timeline, pacing


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
    """Start of a section: a scene (``scene_id``) or the end card (``None``).

    With ``timelapse``, the scene is shown that many times faster until its
    :class:`TimelapseEnd`.
    """

    scene_id: str | None
    hidden: bool = False
    timelapse: float | None = None


@dataclass(frozen=True)
class TimelapseEnd:
    """End of a timelapse scene; its last frame is held for the narration.

    See :func:`narratty.timeline.timelapse_layout` for ``hold_ms`` and ``narration_after``.
    """

    scene_id: str
    hold_ms: int
    narration_after: bool = False


@dataclass(frozen=True)
class Cue:
    """A point in time to remember (where an overlay starts, where the last scene ends)."""

    label: str


Step = Type | Press | Ctrl | Sleep | WaitScreen | Hide | Show | Mark | TimelapseEnd | Cue

END_CUE = "end"

END_CARD_TIMEOUT_MS = 30_000
LAYOUT_TIMEOUT_MS = 15_000
BASELINE_TIMEOUT_MS = 300_000
# Pane titles of the editor layout; the setup waits for the terminal's.
EXPLORER_TITLE, TERMINAL_TITLE = "Explorer", "Terminal"
PANES = {"explorer": ":.1", "terminal": ":.2"}


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


def _then_sleep(steps: list[Step], ms: int) -> list[Step]:
    return [*steps, Sleep(ms)] if ms else steps


def action_steps(action: Action, pace: Pacing, context: Context | None = None) -> list[Step]:
    """Steps for one action (``hold: auto`` is placed by the caller)."""
    context = context or Context(editor=False, python=sys.executable)
    if isinstance(action, Diff):
        return diff_steps(action, context)
    if isinstance(action, Focus | Reveal):
        return editor_steps(action, context)
    speed = pace.speed
    if isinstance(action, Run):
        return _then_sleep([Type(action.run, speed), Press("Enter", speed)], pace.run_hold_ms)
    if isinstance(action, TypeCommand):
        return [Type(action.type_command, speed)]
    if isinstance(action, Enter):
        return _then_sleep([Press("Enter", speed)], pace.pause_ms)
    if isinstance(action, Key):
        name, _, count = action.key.partition(" ")
        return _then_sleep([Press(name, speed, int(count) if count else None)], pace.pause_ms)
    if isinstance(action, CtrlSequence):
        return _then_sleep([Ctrl(action.ctrl_sequence.removeprefix("C-").upper())], pace.pause_ms)
    if isinstance(action, Wait):
        return [WaitScreen(action.wait.screen, action.wait.timeout_ms)]
    if isinstance(action, Hold) and action.hold != "auto":
        return [Sleep(action.hold)]
    return []


def overlay_cue(scene_id: str, index: int) -> str:
    """Label of the cue where the overlay at ``actions[index]`` of a scene starts."""
    return f"overlay:{scene_id}:{index}"


def _sends_keys(action: Action) -> bool:
    return not isinstance(action, Hold | Wait | ShowOverlay)


def _unhide(steps: list[Step]) -> list[Step]:
    """Inside a hidden scene, the steps without their own Hide/Show."""
    return [step for step in steps if not isinstance(step, Hide | Show)]


def _end_hidden(steps: list[Step], context: Context) -> list[Step]:
    """A hidden scene's steps (Mark, Hide, ...): one Hide, then clear and Show."""
    steps = [steps[0], steps[1], *_unhide(steps[2:])]
    # Clear what the hidden commands printed; hidden time is not recorded.
    if context.editor:
        return [*steps, *tmux_command("send-keys -t :.2 clear Enter"), Sleep(300), Show()]
    return [*steps, Type("clear", 1), Press("Enter", 1), Sleep(300), Show()]


def _timelapse_steps(scene: Scene, timing: SceneTiming, pace: Pacing, context: Context) -> list[Step]:
    """A timelapse scene: its actions between markers, the end holds for the narration."""
    actions = [
        step
        for index, action in enumerate(scene.actions)
        for step in (
            [Cue(overlay_cue(scene.id, index))]
            if isinstance(action, ShowOverlay)
            else action_steps(action, pace, context)
        )
    ]
    if context.editor and any(isinstance(action, Diff) for action in scene.actions):
        actions += close_popup()
    end = TimelapseEnd(scene.id, timing.hold_ms, timing.narration_after)
    return [Mark(scene.id, timelapse=timing.timelapse), *actions, end]


def scene_steps(spec: Spec, scene: Scene, timing: SceneTiming, *, python: str | None = None) -> list[Step]:
    """Steps for one scene, with its fill pause at ``hold: auto`` or at the end.

    In the editor layout a diff popup stays open until the next action that sends
    keys, or the end of the scene.
    """
    pace = pacing(spec, scene)
    context = Context(spec.terminal.layout == "editor", python or sys.executable)
    if timing.timelapse:
        return _timelapse_steps(scene, timing, pace, context)
    fill_at_hold = scene.narration_start == "with_actions"
    steps: list[Step] = [Mark(scene.id, scene.hidden)]
    if scene.hidden:
        steps.append(Hide())
    filled = popup = False
    for index, action in enumerate(scene.actions):
        if isinstance(action, ShowOverlay):
            steps.append(Cue(overlay_cue(scene.id, index)))
            continue
        if isinstance(action, Hold) and action.hold == "auto" and fill_at_hold:
            if timing.fill_ms:
                steps.append(Sleep(timing.fill_ms))
            filled = True
            continue
        if popup and _sends_keys(action):
            steps += close_popup()
            popup = False
        steps += action_steps(action, pace, context)
        popup = popup or (context.editor and isinstance(action, Diff))
    if not filled and timing.fill_ms:
        steps.append(Sleep(timing.fill_ms))
    if popup:
        steps += close_popup()
    return _end_hidden(steps, context) if scene.hidden else steps


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


def setup_steps(spec: Spec, python: str | None = None, exit_log: Path | None = None) -> list[Step]:
    """Unrecorded: record the diff baseline, set the prompt, clear, build the layout.

    With ``exit_log``, the demo's shell also logs its commands' exit codes there (in the
    editor layout, the shell in the terminal pane).
    """
    term = spec.terminal
    python = python or sys.executable
    steps: list[Step] = [Hide()]
    if spec.uses_diff:
        steps += [Type(_module(python, "diff", "start"), 1), Press("Enter", 1)]
        steps.append(WaitScreen(DIFF_READY, BASELINE_TIMEOUT_MS))
    # The pause is hidden, so it costs no time; it lets `clear` finish.
    editor = term.layout == "editor"
    setup = prompt_setup(term.shell, term.prompt, None if editor else exit_log)
    steps += [Type(setup, 1), Press("Enter", 1), Sleep(500)]
    if editor:
        start = _module(
            python, "editor", "start", "--shell", term.shell, "--prompt", _shell_quote(term.prompt)
        )
        if exit_log:
            start += f" --exit-log {_shell_quote(str(exit_log))}"
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


def build_script(
    spec: Spec, timeline: Timeline, *, python: str | None = None, exit_log: Path | None = None
) -> list[Step]:
    """Every step of the recording, from prompt setup to the end card.

    ``python`` is the interpreter that draws the end card (default: the running one);
    ``exit_log`` receives the commands' exit codes (see ``narratty.render.exits``).
    """
    python = python or sys.executable
    steps = setup_steps(spec, python, exit_log)
    if timeline.lead_in_ms:
        steps.append(Sleep(timeline.lead_in_ms))
    for scene in spec.scenes:
        steps += scene_steps(spec, scene, timeline.scene(scene.id), python=python)
    steps.append(Cue(END_CUE))
    if timeline.tail_ms:
        steps.append(Sleep(timeline.tail_ms))
    if timeline.end_card_ms:
        steps += teardown_steps(spec) + end_card_steps(spec, timeline, python)
    return steps
