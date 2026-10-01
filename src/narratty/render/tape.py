"""Generate a byte-stable VHS tape from a spec and its timeline."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from narratty.render.pauses import SETTLE_MS, Pause, command_keyword
from narratty.render.script import (
    Ctrl,
    Hide,
    Mark,
    Press,
    Show,
    Sleep,
    Step,
    Type,
    WaitScreen,
    end_card_steps,
    prompt_setup,
    scene_steps,
    setup_steps,
)
from narratty.spec.model import Spec
from narratty.timeline import Timeline

__all__ = ["FRAMERATE", "Tape", "build_tape", "generate_tape", "prompt_setup", "quote_chunks"]

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


def step_lines(step: Step) -> list[str]:
    """VHS commands for one step."""
    match step:
        case Type(text, speed):
            return [f"Type@{speed}ms {literal}" for literal in quote_chunks(text)]
        case Press(key, speed, count):
            return [f"{key}@{speed}ms" + (f" {count}" if count else "")]
        case Ctrl(char):
            return [f"Ctrl+{char}"]
        case Sleep(ms):
            return [f"Sleep {ms}ms"]
        case WaitScreen(pattern, timeout_ms):
            return [f"Wait+Screen@{timeout_ms}ms /{pattern.replace('/', '\\/')}/"]
        case Hide():
            return ["Hide"]
        case Show():
            return ["Show"]
        case Mark(None):
            return ["# end card"]
        case Mark(scene_id, hidden):
            return [f"# scene: {scene_id}" + (" (hidden)" if hidden else "")]
    raise AssertionError(step)  # pragma: no cover


class _Writer:
    """Tape lines, the commands among them and, with ``fast``, the shortened pauses."""

    def __init__(self, fast: bool) -> None:
        self.fast = fast
        self.lines: list[str] = []
        self.commands: list[str] = []
        self.pauses: list[Pause] = []
        self._hidden = False
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
                case Mark(scene_id):
                    self._scene, self._scene_command = scene_id, len(self.commands)
                case Sleep(ms) if self.fast and not self._hidden and ms > SETTLE_MS:
                    self.pauses.append(Pause(len(self.commands), ms, self._scene, self._scene_command))
                    step = Sleep(SETTLE_MS)
            self.raw(*step_lines(step))


@dataclass(frozen=True)
class Tape:
    """A tape, its commands' keywords (as VHS prints them) and its shortened pauses."""

    text: str
    commands: tuple[str, ...]
    pauses: tuple[Pause, ...]


def generate_tape(
    spec: Spec, timeline: Timeline, output: Path, *, python: str | None = None, framerate: int = FRAMERATE
) -> str:
    """The complete tape rendering ``spec`` into ``output``.

    ``python`` is the interpreter that draws the end card (default: the running one).
    """
    return build_tape(spec, timeline, output, python=python, framerate=framerate).text


def build_tape(
    spec: Spec,
    timeline: Timeline,
    output: Path,
    *,
    python: str | None = None,
    framerate: int = FRAMERATE,
    fast: bool = False,
) -> Tape:
    """The tape rendering ``spec`` into ``output``; ``fast`` shortens long pauses (see ``pauses``)."""
    term = spec.terminal
    tape = _Writer(fast)
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
    if fast:
        tape.raw("Set CursorBlink false")  # a repeated frame would stop the blinking
    tape.raw("")
    tape.steps(setup_steps(spec))
    if timeline.lead_in_ms:
        tape.steps([Sleep(timeline.lead_in_ms)])
    for scene in spec.scenes:
        tape.raw("")
        tape.steps(scene_steps(spec, scene, timeline.scene(scene.id)))
    tape.raw("")
    if timeline.tail_ms:
        tape.steps([Sleep(timeline.tail_ms)])
    if timeline.end_card_ms:
        tape.raw("")
        tape.steps(end_card_steps(spec, timeline, python or sys.executable))
    return Tape("\n".join(tape.lines) + "\n", tuple(tape.commands), tuple(tape.pauses))
