"""Generate a byte-stable VHS tape from a spec and its timeline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from narratty.end_card import CREDIT
from narratty.spec.model import Action, CtrlSequence, Enter, Hold, Key, Scene, Spec, TypeCommand, Wait
from narratty.timeline import SceneTiming, Timeline, typing_speed

FRAMERATE = 30
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


def _type(text: str, speed: int) -> list[str]:
    return [f"Type@{speed}ms {literal}" for literal in quote_chunks(text)]


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def prompt_setup(shell: str, prompt: str) -> str:
    """Shell command that sets a fixed prompt and clears the screen."""
    if shell == "fish":
        return f"function fish_prompt; printf '%s' {_shell_quote(prompt)}; end; clear"
    return f"PS1={_shell_quote(prompt)}; clear"


def action_lines(action: Action, speed: int) -> list[str]:
    """VHS commands for one action (``hold: auto`` is emitted by the caller)."""
    if isinstance(action, TypeCommand):
        return _type(action.type_command, speed)
    if isinstance(action, Enter):
        return [f"Enter@{speed}ms"]
    if isinstance(action, Key):
        name, _, count = action.key.partition(" ")
        return [f"{name}@{speed}ms" + (f" {count}" if count else "")]
    if isinstance(action, CtrlSequence):
        return [f"Ctrl+{action.ctrl_sequence.removeprefix('C-').upper()}"]
    if isinstance(action, Wait):
        pattern = action.wait.screen.replace("/", "\\/")
        return [f"Wait+Screen@{action.wait.timeout_ms}ms /{pattern}/"]
    if isinstance(action, Hold) and action.hold != "auto":
        return [f"Sleep {action.hold}ms"]
    return []


def _scene_lines(spec: Spec, scene: Scene, timing: SceneTiming) -> list[str]:
    speed = typing_speed(spec, scene)
    fill_at_hold = scene.narration_start == "with_actions"
    lines = [f"# scene: {scene.id}" + (" (hidden)" if scene.hidden else "")]
    if scene.hidden:
        lines.append("Hide")
    filled = False
    for action in scene.actions:
        if isinstance(action, Hold) and action.hold == "auto" and fill_at_hold:
            if timing.fill_ms:
                lines.append(f"Sleep {timing.fill_ms}ms")
            filled = True
            continue
        lines += action_lines(action, speed)
    if not filled and timing.fill_ms:
        lines.append(f"Sleep {timing.fill_ms}ms")
    if scene.hidden:
        # Clear what the hidden commands printed; hidden time is not recorded.
        lines += ['Type@1ms "clear"', "Enter@1ms", "Sleep 300ms", "Show"]
    return lines


def end_card_lines(spec: Spec, timeline: Timeline, python: str) -> list[str]:
    """Draw the end card while hidden, then keep it on screen for its duration."""
    command = f"{prompt_setup(spec.terminal.shell, '')}; {_shell_quote(python)} -m narratty.end_card"
    if not spec.end_card.qr:
        command += " --no-qr"
    return [
        "# end card",
        "Hide",
        *_type(command, 1),
        "Enter@1ms",
        f"Wait+Screen@30s /{CREDIT}/",
        "Show",
        f"Sleep {timeline.end_card_ms}ms",
    ]


def generate_tape(spec: Spec, timeline: Timeline, output: Path, *, python: str | None = None) -> str:
    """The complete tape rendering ``spec`` into ``output``.

    ``python`` is the interpreter that draws the end card (default: the running one).
    """
    term = spec.terminal
    lines = [
        f"# narratty tape for {json.dumps(spec.meta.title)}",
        f"Output {json.dumps(str(output))}",
        f"Set Shell {term.shell}",
        f"Set Width {term.width}",
        f"Set Height {term.height}",
        f"Set FontSize {term.font_size}",
        f"Set Theme {json.dumps(term.theme)}",
        f"Set TypingSpeed {term.typing_speed_ms}ms",
        f"Set Framerate {FRAMERATE}",
        "",
        "Hide",
        *_type(prompt_setup(term.shell, term.prompt), 1),
        "Enter@1ms",
        "Sleep 500ms",  # hidden, so it costs no video time; lets `clear` finish
        "Show",
    ]
    if timeline.lead_in_ms:
        lines.append(f"Sleep {timeline.lead_in_ms}ms")
    for scene in spec.scenes:
        lines.append("")
        lines += _scene_lines(spec, scene, timeline.scene(scene.id))
    lines.append("")
    if timeline.tail_ms:
        lines.append(f"Sleep {timeline.tail_ms}ms")
    if timeline.end_card_ms:
        lines += ["", *end_card_lines(spec, timeline, python or sys.executable)]
    return "\n".join(lines) + "\n"
