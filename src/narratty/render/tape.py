"""Generate a byte-stable VHS tape from a spec and its timeline."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from pathlib import Path

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

__all__ = ["FRAMERATE", "generate_tape", "prompt_setup", "quote_chunks"]

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


def _lines(steps: Iterable[Step]) -> list[str]:
    return [line for step in steps for line in step_lines(step)]


def generate_tape(
    spec: Spec, timeline: Timeline, output: Path, *, python: str | None = None, remote: bool = False
) -> str:
    """The complete tape rendering ``spec`` into ``output``.

    ``python`` is the interpreter that draws the end card (default: the running one);
    ``remote`` says the shell runs in a project environment.
    """
    term = spec.terminal
    lines = [
        f"# narratty tape for {json.dumps(spec.meta.title)}",
        f"Output {json.dumps(str(output))}",
        f"Set Shell {term.shell}",
        f"Set Width {term.width}",
        f"Set Height {term.height}",
        f"Set FontSize {term.font_size}",
        f"Set FontFamily {json.dumps(FONT_FAMILY)}",
        f"Set Theme {json.dumps(term.theme)}",
        f"Set TypingSpeed {term.typing_speed_ms}ms",
        f"Set Framerate {FRAMERATE}",
        "",
        *_lines(setup_steps(spec)),
    ]
    if timeline.lead_in_ms:
        lines.append(f"Sleep {timeline.lead_in_ms}ms")
    for scene in spec.scenes:
        lines += ["", *_lines(scene_steps(spec, scene, timeline.scene(scene.id)))]
    lines.append("")
    if timeline.tail_ms:
        lines.append(f"Sleep {timeline.tail_ms}ms")
    if timeline.end_card_ms:
        lines += ["", *_lines(end_card_steps(spec, timeline, python or sys.executable, remote=remote))]
    return "\n".join(lines) + "\n"
