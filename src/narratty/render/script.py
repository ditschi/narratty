"""The recording script: what to type, press and wait for, in order.

Both recorders run it: ``tape`` turns it into a VHS tape, ``cast`` plays it in a
pseudo-terminal. Generating it once keeps the two in step.
"""

from __future__ import annotations

import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from narratty import diff, editor, sh
from narratty.editor import TERMINAL_TITLE
from narratty.end_card import CREDIT
from narratty.render.pauses import SETTLE_MS
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
    ShowBrowser,
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
    """Pause. ``replayed``: a replayed scene's pause of that length, cut short."""

    ms: int
    replayed: int = 0


@dataclass(frozen=True)
class WaitScreen:
    """Block until the screen (or with ``line``, the cursor's line) matches ``pattern``.

    With ``fail``, a screen matching it ends the wait at once and fails the build; its
    first group is the message.
    """

    pattern: str
    timeout_ms: int
    line: bool = False
    fail: str | None = None


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
    :class:`TimelapseEnd`. ``fast`` is the scene's own choice about fast pauses
    (None: the build's).
    """

    scene_id: str | None
    hidden: bool = False
    timelapse: float | None = None
    fast: bool | None = None


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

# Section labels besides the scene ids (which cannot contain a colon).
SETUP, HEAD, TAIL, CARD = ":setup", ":head", ":tail", ":card"
REPLAY_TYPING_MS = 5
REPLAY_SETTLE_MS = 300

END_CARD_TIMEOUT_MS = 30_000
LAYOUT_TIMEOUT_MS = 15_000
BASELINE_TIMEOUT_MS = 300_000
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


def prompt_pattern(prompt: str) -> str:
    """A line holding only ``prompt`` (RE2 and Python syntax): the last command has finished."""
    escaped = re.sub(r"([\\.^$|?*+()\[\]{}])", r"\\\1", prompt.rstrip())
    return f"^{escaped}\\s*$"


def hidden(steps: list[Step], settle_ms: int = 300) -> list[Step]:
    """``steps`` unrecorded, then ``settle_ms`` for the screen to catch up."""
    return [Hide(), *steps, Sleep(settle_ms), Show()]


def tmux_command(command: str) -> list[Step]:
    """Run a tmux command through its prompt (``Ctrl+b :``), whatever pane has focus."""
    return [Ctrl("B"), Type(":", 1), Type(command, 1), Press("Enter", 1)]


def _default_diff_base() -> str:
    return str(Path(tempfile.gettempdir()) / "narratty-diff")


@dataclass(frozen=True)
class HelperPlacement:
    """Where the parts of the demo run, decided by ``narratty.build``.

    ``diff_base`` is the diff baseline's directory, on the side that runs the diff
    commands. ``terminal`` is the editor layout's terminal pane command (default: the
    shell); with a project environment whose workspace narratty shares, it is the
    bridge, so tmux and yazi run here and only the shell runs there. ``bridged``: the
    recorder's own shell is the project environment's. ``where`` names that side in
    the message about a missing tool.
    """

    diff_base: str = field(default_factory=_default_diff_base)
    terminal: str | None = None
    bridged: bool = False
    where: str = "on this machine"

    def shell(self, spec: Spec) -> str:
        """The recorder's own shell: ``bash`` when the terminal pane is a bridge (the
        spec's shell may only exist in the environment), else the spec's. VHS's
        ``Set Shell`` rejects ``sh``; ``bash`` is on the narratty image."""
        return "bash" if self.terminal else spec.terminal.shell


@dataclass(frozen=True)
class Context:
    """What action steps depend on beyond the action: the layout, where its helpers run
    and the prompt (``wait: {prompt: true}`` waits for it)."""

    editor: bool
    placement: HelperPlacement = field(default_factory=HelperPlacement)
    prompt: str = "$ "


def diff_steps(action: Diff, context: Context) -> list[Step]:
    """Show the diff: a popup in the editor layout, else printed in the shell."""
    base = context.placement.diff_base
    if context.editor:
        show = sh.tmux_arg(diff.show_script(base, action.paths, wait=True))
        popup = f'display-popup -E -w 90% -h 85% -T " Diff " {show}'
        return hidden(tmux_command(popup), 1000)
    show = sh.command(diff.show_script(base, action.paths))
    return hidden([Type(f"clear; {show}", 1), Press("Enter", 1)], 1000)


def close_popup() -> list[Step]:
    """Close the diff popup (it waits for Enter)."""
    return hidden([Press("Enter", 1)])


def editor_steps(action: Focus | Reveal, context: Context) -> list[Step]:
    """Steps for the editor layout's own actions."""
    if isinstance(action, Focus):
        return hidden(tmux_command(f"select-pane -t {PANES[action.focus]}"), 100)
    reveal = sh.tmux_arg(editor.reveal_script(action.reveal))
    return hidden(tmux_command(f"run-shell {reveal}"), 600)


def _then_sleep(steps: list[Step], ms: int) -> list[Step]:
    return [*steps, Sleep(ms)] if ms else steps


def _key_steps(action: Enter | Key | CtrlSequence, speed: int) -> list[Step]:
    if isinstance(action, Enter):
        return [Press("Enter", speed)]
    if isinstance(action, Key):
        name, _, count = action.key.partition(" ")
        return [Press(name, speed, int(count) if count else None)]
    return [Ctrl(action.ctrl_sequence.removeprefix("C-").upper())]


def action_steps(action: Action, pace: Pacing, context: Context | None = None) -> list[Step]:
    """Steps for one action (``hold: auto`` is placed by the caller)."""
    context = context or Context(editor=False)
    if isinstance(action, Diff):
        return diff_steps(action, context)
    if isinstance(action, Focus | Reveal):
        return editor_steps(action, context)
    speed = pace.speed
    if isinstance(action, Run):
        return _then_sleep([Type(action.run, speed), Press("Enter", speed)], pace.run_hold_ms)
    if isinstance(action, TypeCommand):
        return [Type(action.type_command, speed)]
    if isinstance(action, Enter | Key | CtrlSequence):
        return _then_sleep(_key_steps(action, speed), pace.pause_ms)
    if isinstance(action, Wait):
        if action.wait.screen is None:
            return [WaitScreen(prompt_pattern(context.prompt), action.wait.timeout_ms, line=True)]
        return [WaitScreen(action.wait.screen, action.wait.timeout_ms)]
    if isinstance(action, Hold) and action.hold != "auto":
        return [Sleep(action.hold)]
    return []


def overlay_cue(scene_id: str, index: int) -> str:
    """Label of the cue where the overlay or browser at ``actions[index]`` of a scene starts."""
    return f"overlay:{scene_id}:{index}"


def _sends_keys(action: Action) -> bool:
    return not isinstance(action, Hold | Wait | ShowOverlay | ShowBrowser)


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
            if isinstance(action, ShowOverlay | ShowBrowser)
            else action_steps(action, pace, context)
        )
    ]
    if context.editor and any(isinstance(action, Diff) for action in scene.actions):
        actions += close_popup()
    end = TimelapseEnd(scene.id, timing.hold_ms, timing.narration_after)
    return [Mark(scene.id, timelapse=timing.timelapse), *actions, end]


def scene_steps(
    spec: Spec, scene: Scene, timing: SceneTiming, *, placement: HelperPlacement | None = None
) -> list[Step]:
    """Steps for one scene, with its fill pause at ``hold: auto`` or at the end.

    In the editor layout a diff popup stays open until the next action that sends
    keys, or the end of the scene.
    """
    pace = pacing(spec, scene)
    context = Context(spec.terminal.layout == "editor", placement or HelperPlacement(), spec.terminal.prompt)
    if timing.timelapse:
        return _timelapse_steps(scene, timing, pace, context)
    fill_at_hold = scene.narration_start == "with_actions"
    steps: list[Step] = [Mark(scene.id, scene.hidden, fast=scene.fast)]
    if scene.hidden:
        steps.append(Hide())
    filled = popup = False
    for index, action in enumerate(scene.actions):
        if isinstance(action, ShowOverlay | ShowBrowser):
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


def end_card_steps(
    spec: Spec, timeline: Timeline, python: str, *, remote: bool = False, local_shell: str | None = None
) -> list[Step]:
    """Draw the end card while hidden, then keep it on screen for its duration.

    ``remote``: the shell runs in a project environment without narratty. Leaving it
    drops to a local ``sh`` (see ``narratty.bridge``), which draws the card.
    ``local_shell``: the recorder's shell, when it is not the spec's.
    """
    shell = "sh" if remote else spec.terminal.shell if local_shell is None else local_shell
    command = f"{prompt_setup(shell, '')}; {_shell_quote(python)} -m narratty.end_card"
    if not spec.end_card.qr:
        command += " --no-qr"
    leave: list[Step] = [Type("exit", 1), Press("Enter", 1), Sleep(500)] if remote else []
    return [
        Mark(None),
        Hide(),
        *leave,
        Type(command, 1),
        Press("Enter", 1),
        WaitScreen(CREDIT, END_CARD_TIMEOUT_MS),
        Show(),
        Sleep(timeline.end_card_ms),
    ]


def setup_steps(
    spec: Spec, placement: HelperPlacement | None = None, exit_log: Path | None = None
) -> list[Step]:
    """Unrecorded: record the diff baseline, set the prompt, clear, build the layout.

    With ``exit_log``, the demo's shell also logs its commands' exit codes there (in the
    editor layout, the shell in the terminal pane).
    """
    term = spec.terminal
    placement = placement or HelperPlacement()
    steps: list[Step] = [Hide()]
    if spec.uses_diff:
        steps += [Type(diff.start_command(placement.diff_base, placement.where), 1), Press("Enter", 1)]
        steps += _wait_or_fail(diff.READY, BASELINE_TIMEOUT_MS)
    # The pause is hidden, so it costs no time; it lets `clear` finish.
    in_editor = term.layout == "editor"
    setup = prompt_setup(placement.shell(spec), term.prompt, None if in_editor else exit_log)
    steps += [Type(setup, 1), Press("Enter", 1), Sleep(500)]
    if in_editor:
        start = editor.start_command(
            term.shell,
            prompt_setup(term.shell, term.prompt, exit_log),
            terminal=placement.terminal,
            where=placement.where,
        )
        steps += [Type(start, 1), Press("Enter", 1), *_wait_or_fail(TERMINAL_TITLE, LAYOUT_TIMEOUT_MS)]
        steps.append(Sleep(1500))
    return [*steps, Show()]


def _wait_or_fail(pattern: str, timeout_ms: int) -> list[Step]:
    """Wait for ``pattern``; a helper's ``narratty error:`` fails the build at once."""
    return [WaitScreen(pattern, timeout_ms, fail=sh.ERROR)]


def teardown_steps(spec: Spec) -> list[Step]:
    """Unrecorded: leave the editor layout, so the end card gets the whole terminal."""
    if spec.terminal.layout != "editor":
        return []
    return hidden(tmux_command("kill-server"), 500)


@dataclass(frozen=True)
class Partial:
    """Record only some sections; see ``narratty.incremental``.

    ``record`` holds the labels recorded as usual: ``HEAD`` (the lead-in), visible scene
    ids, ``TAIL`` (the tail) and ``CARD`` (the end card). The other visible scenes up to ``last`` are
    replayed (:func:`replay_steps`), those in ``realtime`` at their own pace. Hidden
    scenes run as usual. Nothing after ``last`` runs.
    """

    record: frozenset[str]
    last: str
    realtime: frozenset[str] = frozenset()


def replay_steps(steps: list[Step], *, realtime: bool = False) -> list[Step]:
    """A visible scene's steps run unrecorded (the caller hides them) and without markers.

    Unless ``realtime``, typing is quick and long pauses are cut to ``SETTLE_MS``; the
    cut pauses are marked so the recorder can check nothing was still running then.
    """
    kept: list[Step] = [step for step in steps if not isinstance(step, Hide | Show | Cue | TimelapseEnd)]
    kept = [Mark(step.scene_id, True, fast=step.fast) if isinstance(step, Mark) else step for step in kept]
    return kept if realtime else quick(kept)


def quick(steps: list[Step]) -> list[Step]:
    """``steps`` with quick typing and long pauses cut short (see :func:`replay_steps`)."""
    quickened: list[Step] = []
    for step in steps:
        match step:
            case Type(text, speed):
                step = Type(text, min(speed, REPLAY_TYPING_MS))
            case Press(key, speed, count):
                step = Press(key, min(speed, REPLAY_TYPING_MS), count)
            case Sleep(ms, 0) if ms > SETTLE_MS:
                step = Sleep(SETTLE_MS, replayed=ms)
        quickened.append(step)
    return quickened


def _full_sections(
    spec: Spec, timeline: Timeline, python: str, exit_log: Path | None, placement: HelperPlacement
) -> list[tuple[str, list[Step], Scene | None]]:
    parts: list[tuple[str, list[Step], Scene | None]] = [
        (SETUP, setup_steps(spec, placement, exit_log), None)
    ]
    if timeline.lead_in_ms:
        parts.append((HEAD, [Sleep(timeline.lead_in_ms)], None))
    for scene in spec.scenes:
        parts.append(
            (scene.id, scene_steps(spec, scene, timeline.scene(scene.id), placement=placement), scene)
        )
    parts.append((TAIL, [Cue(END_CUE), *([Sleep(timeline.tail_ms)] if timeline.tail_ms else [])], None))
    if timeline.end_card_ms:
        card = end_card_steps(
            spec, timeline, python, remote=placement.bridged, local_shell=placement.shell(spec)
        )
        parts.append((CARD, teardown_steps(spec) + card, None))
    return parts


def sections(
    spec: Spec,
    timeline: Timeline,
    *,
    python: str | None = None,
    exit_log: Path | None = None,
    placement: HelperPlacement | None = None,
    partial: Partial | None = None,
) -> list[tuple[str, list[Step]]]:
    """The script's steps by section: ``SETUP``, ``HEAD``, each scene, ``TAIL``, ``CARD``.

    With ``partial``, only some sections are recorded and the script ends after the last
    of them (see :class:`Partial`); recording stays off until the first.
    """
    full = _full_sections(spec, timeline, python or sys.executable, exit_log, placement or HelperPlacement())
    if partial is None:
        return [(label, steps) for label, steps, _ in full]
    parts: list[tuple[str, list[Step]]] = []
    hiding = True
    for label, steps, scene in full:
        if label == SETUP:
            parts.append((label, steps[:-1]))  # its closing Show waits for the first recorded section
        elif label in partial.record:
            parts.append((label, [Sleep(REPLAY_SETTLE_MS), Show(), *steps] if hiding else steps))
            hiding = False
        elif scene is not None:
            parts.append((label, _unrecorded(scene, steps, partial, hiding=hiding)))
            hiding = hiding or not scene.hidden
        elif label == TAIL:
            parts.append((label, [] if hiding else [Hide()]))
            hiding = True
        if label == partial.last:
            break
    return parts


def _unrecorded(scene: Scene, steps: list[Step], partial: Partial, *, hiding: bool) -> list[Step]:
    """A scene that runs without being recorded: hidden ones as usual, visible ones replayed."""
    if scene.hidden:
        steps = steps if scene.id in partial.realtime else quick(steps)
        return _unhide(steps) if hiding else steps
    replayed = replay_steps(steps, realtime=scene.id in partial.realtime)
    return replayed if hiding else [Hide(), *replayed]


def build_script(
    spec: Spec,
    timeline: Timeline,
    *,
    python: str | None = None,
    exit_log: Path | None = None,
    placement: HelperPlacement | None = None,
    partial: Partial | None = None,
) -> list[Step]:
    """Every step of the recording, from prompt setup to the end card.

    ``python`` is the interpreter that draws the end card (default: the running one);
    ``exit_log`` receives the commands' exit codes (see ``narratty.render.exits``);
    ``placement`` says where the shell and the helpers run; ``partial`` records only
    some sections.
    """
    parts = sections(spec, timeline, python=python, exit_log=exit_log, placement=placement, partial=partial)
    return [step for _, steps in parts for step in steps]
