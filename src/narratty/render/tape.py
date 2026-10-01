"""Generate a byte-stable VHS tape from a spec and its timeline."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from narratty.render.pauses import SETTLE_MS, Pause, command_keyword
from narratty.render.script import (
    END_CUE,
    Ctrl,
    Cue,
    Hide,
    Mark,
    Press,
    Show,
    Sleep,
    Step,
    TimelapseEnd,
    Type,
    WaitScreen,
    end_card_steps,
    prompt_setup,
    scene_steps,
    setup_steps,
    teardown_steps,
)
from narratty.spec.model import Spec
from narratty.timeline import Timeline

__all__ = ["FRAMERATE", "Tape", "build_tape", "generate_tape", "prompt_setup", "quote_chunks", "uses_fast"]

FRAMERATE = 30
# VHS's default font list plus a Nerd Font fallback, so icons (yazi, eza --icons) render
# when the toolkit's Symbols Nerd Font is installed. Chromium does not fall back to it
# on its own.
FONT_FAMILY = (
    "JetBrains Mono,DejaVu Sans Mono,Menlo,Bitstream Vera Sans Mono,Inconsolata,"
    "Roboto Mono,Hack,Consolas,ui-monospace,Symbols Nerd Font Mono,monospace"
)
_DELIMITERS = ('"', "'", "`")


def quote_chunks(text: str) -> list[str]:
    """Split ``text`` into VHS string literals.

    VHS strings have no escapes, only three possible delimiters, so text containing
    all of them is split into several literals.
    """
    chunks: list[str] = []
    current = ""
    usable = list(_DELIMITERS)
    for char in text:
        remaining = [d for d in usable if d != char]
        if not remaining:
            chunks.append(f"{usable[0]}{current}{usable[0]}")
            current, remaining = "", [d for d in _DELIMITERS if d != char]
        current += char
        usable = remaining
    chunks.append(f"{usable[0]}{current}{usable[0]}")
    return chunks


def marker_path(marks: Path, label: str) -> Path:
    """The screenshot that marks ``label`` (see ``narratty.render.timelapse``)."""
    return marks / f"{label}.png"


def _marker(marks: Path | None, label: str) -> list[str]:
    return [] if marks is None else [f"Screenshot {json.dumps(str(marker_path(marks, label)))}"]


def step_lines(step: Step, marks: Path | None = None) -> list[str]:
    """VHS commands for one step.

    With ``marks``, visible scene starts, timelapse ends and cues take a screenshot there;
    VHS logs it as it happens, which locates it in the video.
    """
    match step:
        case Type(text, speed):
            return [f"Type@{speed}ms {literal}" for literal in quote_chunks(text)]
        case Press(key, speed, count):
            return [f"{key}@{speed}ms" + (f" {count}" if count else "")]
        case Ctrl(char):
            return [f"Ctrl+{char}"]
        case Sleep(ms):
            return [f"Sleep {ms}ms"]
        case WaitScreen(pattern, timeout_ms, line):
            scope = "Line" if line else "Screen"
            return [f"Wait+{scope}@{timeout_ms}ms /{pattern.replace('/', '\\/')}/"]
        case Hide():
            return ["Hide"]
        case Show():
            return ["Show"]
        case Cue(label):
            return [f"# cue: {label}", *_marker(marks, f"cue-{label}")]
        case Mark() | TimelapseEnd():
            return _section_lines(step, marks)
    raise AssertionError(step)  # pragma: no cover


def _section_lines(step: Mark | TimelapseEnd, marks: Path | None) -> list[str]:
    match step:
        case Mark(None):
            return ["# end card"]
        case Mark(scene_id, True):
            return [f"# scene: {scene_id} (hidden)"]
        case Mark(scene_id, False, timelapse):
            comment = f"# scene: {scene_id}" + (f" (timelapse ×{timelapse:g})" if timelapse else "")
            return [comment, *_marker(marks, f"scene-{scene_id}")]
        case TimelapseEnd(scene_id):
            return [f"# timelapse end: {scene_id}", *_marker(marks, f"end-{scene_id}")]
    raise AssertionError(step)  # pragma: no cover


class _Writer:
    """Tape lines, the commands among them and, with ``fast``, the shortened pauses.

    A scene's own ``fast`` overrides the build's. Pauses in timelapse scenes are not
    shortened; those scenes are sped up anyway.
    """

    def __init__(self, fast: bool, marks: Path | None = None) -> None:
        self.fast = fast
        self.marks = marks
        self.lines: list[str] = []
        self.commands: list[str] = []
        self.pauses: list[Pause] = []
        self._hidden = False
        self._scene_fast = fast
        self._timelapse = False
        self._scene: str | None = None
        self._scene_command = 0

    def raw(self, *lines: str) -> None:
        for line in lines:
            self.lines.append(line)
            if line and not line.startswith("#"):
                self.commands.append(command_keyword(line))

    def steps(self, steps: Iterable[Step]) -> None:
        for step in steps:
            match step:
                case Hide() | Show():
                    self._hidden = isinstance(step, Hide)
                case Mark(scene_id, _, timelapse, scene_fast):
                    self._scene, self._scene_command = scene_id, len(self.commands)
                    self._timelapse = bool(timelapse)
                    self._scene_fast = self.fast if scene_fast is None else scene_fast
                case TimelapseEnd():
                    self._timelapse = False
                case Sleep(ms) if self._shortens(ms):
                    self.pauses.append(Pause(len(self.commands), ms, self._scene, self._scene_command))
                    step = Sleep(SETTLE_MS)
            self.raw(*step_lines(step, self.marks))

    def _shortens(self, ms: int) -> bool:
        return self._scene_fast and not self._hidden and not self._timelapse and ms > SETTLE_MS


@dataclass(frozen=True)
class Tape:
    """A tape, its commands' keywords (as VHS prints them) and its shortened pauses."""

    text: str
    commands: tuple[str, ...]
    pauses: tuple[Pause, ...]


def uses_fast(spec: Spec, fast: bool) -> bool:
    """Whether any scene may have its pauses shortened."""
    return any(fast if scene.fast is None else scene.fast for scene in spec.scenes)


def generate_tape(
    spec: Spec,
    timeline: Timeline,
    output: Path,
    *,
    python: str | None = None,
    framerate: int = FRAMERATE,
    marks: Path | None = None,
    exit_log: Path | None = None,
    remote: bool = False,
) -> str:
    """The complete tape rendering ``spec`` into ``output``.

    ``python`` is the interpreter that runs narratty's helpers in the recorded shell
    (default: the running one). ``marks`` is where scene markers go (needed to speed
    up timelapse scenes). ``exit_log`` receives the commands' exit codes (see
    ``narratty.render.exits``). ``remote`` says the shell runs in a project environment.
    """
    tape = build_tape(
        spec,
        timeline,
        output,
        python=python,
        framerate=framerate,
        marks=marks,
        exit_log=exit_log,
        remote=remote,
    )
    return tape.text


def build_tape(
    spec: Spec,
    timeline: Timeline,
    output: Path,
    *,
    python: str | None = None,
    framerate: int = FRAMERATE,
    marks: Path | None = None,
    exit_log: Path | None = None,
    remote: bool = False,
    fast: bool = False,
) -> Tape:
    """The tape rendering ``spec`` into ``output`` (see :func:`generate_tape`).

    ``fast`` shortens long pauses (see ``narratty.render.pauses``); a scene's own
    ``fast`` overrides it.
    """
    term = spec.terminal
    tape = _Writer(fast, marks)
    tape.raw(
        f"# narratty tape for {json.dumps(spec.meta.title)}",
        f"Output {json.dumps(str(output))}",
        f"Set Shell {term.shell}",
        f"Set Width {term.width}",
        f"Set Height {term.height}",
        f"Set FontSize {term.font_size}",
        f"Set FontFamily {json.dumps(FONT_FAMILY)}",
        f"Set Theme {json.dumps(term.theme)}",
        f"Set TypingSpeed {term.typing_speed_ms}ms",
        f"Set Framerate {framerate}",
    )
    if uses_fast(spec, fast):
        tape.raw("Set CursorBlink false")  # a repeated frame would stop the blinking
    tape.raw("")
    python = python or sys.executable
    tape.steps(setup_steps(spec, python, exit_log))
    if timeline.lead_in_ms:
        tape.steps([Sleep(timeline.lead_in_ms)])
    for scene in spec.scenes:
        tape.raw("")
        tape.steps(scene_steps(spec, scene, timeline.scene(scene.id), python=python))
    tape.raw("")
    tape.steps([Cue(END_CUE)])
    if timeline.tail_ms:
        tape.steps([Sleep(timeline.tail_ms)])
    if timeline.end_card_ms:
        tape.raw("")
        tape.steps(teardown_steps(spec) + end_card_steps(spec, timeline, python, remote=remote))
    return Tape("\n".join(tape.lines) + "\n", tuple(tape.commands), tuple(tape.pauses))
