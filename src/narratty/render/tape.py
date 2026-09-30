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
    TimelapseEnd,
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


def marker_path(marks: Path, label: str) -> Path:
    """The screenshot that marks ``label`` (see ``narratty.render.timelapse``)."""
    return marks / f"{label}.png"


def _marker(marks: Path | None, label: str) -> list[str]:
    return [] if marks is None else [f"Screenshot {json.dumps(str(marker_path(marks, label)))}"]


def step_lines(step: Step, marks: Path | None = None) -> list[str]:
    """VHS commands for one step.

    With ``marks``, visible scene starts and timelapse ends take a screenshot there;
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
        case WaitScreen(pattern, timeout_ms):
            return [f"Wait+Screen@{timeout_ms}ms /{pattern.replace('/', '\\/')}/"]
        case Hide():
            return ["Hide"]
        case Show():
            return ["Show"]
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


def _lines(steps: Iterable[Step], marks: Path | None = None) -> list[str]:
    return [line for step in steps for line in step_lines(step, marks)]


def generate_tape(
    spec: Spec, timeline: Timeline, output: Path, *, python: str | None = None, marks: Path | None = None
) -> str:
    """The complete tape rendering ``spec`` into ``output``.

    ``python`` is the interpreter that draws the end card (default: the running one).
    ``marks`` is where scene markers go (needed to speed up timelapse scenes).
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
        lines += ["", *_lines(scene_steps(spec, scene, timeline.scene(scene.id)), marks)]
    lines.append("")
    if timeline.tail_ms:
        lines.append(f"Sleep {timeline.tail_ms}ms")
    if timeline.end_card_ms:
        lines += ["", *_lines(end_card_steps(spec, timeline, python or sys.executable))]
    return "\n".join(lines) + "\n"
