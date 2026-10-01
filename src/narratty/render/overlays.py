"""Text overlays: chapter titles, file names and other text shown over the video.

An ``overlay`` action marks a point in its scene. The overlay shows from there until
the first of: its ``duration_ms`` has passed, another overlay takes its position, or
its scene ends (with ``keep``: the last scene). Styles layer: the built-in ``default``,
then ``overlay_styles.default``, then the named style, then the overlay's own keys.

The mp4 gets each overlay as a PNG (drawn with Pillow, sized around its text) that
ffmpeg fades in and out over the picture. The cast page shows them as HTML boxes timed
by the player's clock.
"""

from __future__ import annotations

import functools
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from narratty.render.script import (
    END_CUE,
    Cue,
    Hide,
    Mark,
    Press,
    Show,
    Sleep,
    Step,
    Type,
    overlay_cue,
)
from narratty.spec.model import Overlay, OverlayStyle, ShowOverlay, Spec, Terminal

BUILTIN_STYLES: dict[str, OverlayStyle] = {
    "default": OverlayStyle(
        position="bottom-right",
        size="medium",
        color="#ffffff",
        background="#000000b3",
        box=True,
        bold=False,
        keep=False,
    ),
    # Top right: command lines rarely reach it.
    "chapter": OverlayStyle(position="top-right", size="large", bold=True, keep=True),
}
SIZES = {"small": 1.0, "medium": 1.3, "large": 1.8}
FADE_MS = 200


@dataclass(frozen=True)
class Look:
    """An overlay's resolved style."""

    position: str
    scale: float
    color: str
    background: str
    box: bool
    bold: bool
    keep: bool
    duration_ms: int | None


def resolve(spec: Spec, overlay: Overlay) -> Look:
    """The look of ``overlay``: built-in default, then ``overlay_styles``, then its own keys."""
    layers = [
        BUILTIN_STYLES["default"],
        spec.overlay_styles.get("default"),
        BUILTIN_STYLES.get(overlay.style) if overlay.style != "default" else None,
        spec.overlay_styles.get(overlay.style) if overlay.style != "default" else None,
        overlay,
    ]
    values: dict[str, Any] = {}
    for layer in layers:
        if layer is not None:
            values |= {
                key: value
                for key, value in layer.model_dump(include=set(OverlayStyle.model_fields)).items()
                if value is not None
            }
    size = values["size"]
    return Look(
        position=values["position"],
        scale=SIZES[size] if isinstance(size, str) else float(size),
        color=values["color"],
        background=values["background"],
        box=values["box"],
        bold=values["bold"],
        keep=values["keep"],
        duration_ms=values.get("duration_ms"),
    )


@dataclass(frozen=True)
class Shown:
    """One overlay as it appears in the output."""

    text: str
    look: Look
    start_ms: int
    end_ms: int


def planned_times(steps: Sequence[Step]) -> dict[str, int]:
    """When each visible scene starts and each cue is reached, by the planned timing.

    Matches the timeline: typing and key presses take their speed per key, sleeps their
    length, waits and control chords nothing; hidden steps take no time.
    """
    times: dict[str, int] = {}
    now, hidden = 0, False
    for step in steps:
        match step:
            case Type(text, speed) if not hidden:
                now += len(text) * speed
            case Press(_, speed, count) if not hidden:
                now += speed * (count or 1)
            case Sleep(ms) if not hidden:
                now += ms
            case Hide():
                hidden = True
            case Show():
                hidden = False
            case Mark(scene_id, scene_hidden) if scene_id is not None and not scene_hidden:
                times[scene_id] = now
            case Cue(label) if not hidden:
                times[label] = now
    return times


def schedule(spec: Spec, times: Mapping[str, int]) -> list[Shown]:
    """Every overlay of ``spec`` with its start and end, given scene and cue ``times``."""
    end = times[END_CUE]
    visible = [scene for scene in spec.scenes if not scene.hidden]
    shown: list[Shown] = []
    for number, scene in enumerate(visible):
        scene_end = times[visible[number + 1].id] if number + 1 < len(visible) else end
        for index, action in enumerate(scene.actions):
            if not isinstance(action, ShowOverlay):
                continue
            look = resolve(spec, action.overlay)
            start = times[overlay_cue(scene.id, index)]
            stop = end if look.keep else scene_end
            if look.duration_ms is not None:
                stop = min(stop, start + look.duration_ms)
            shown.append(Shown(action.overlay.text, look, start, stop))
    # A later overlay at the same position replaces an earlier one.
    for number, item in enumerate(shown):
        for later in shown[number + 1 :]:
            if later.look.position == item.look.position and later.start_ms < item.end_ms:
                shown[number] = item = Shown(item.text, item.look, item.start_ms, later.start_ms)
                break
    return [item for item in shown if item.end_ms > item.start_ms]


def scaled(shown: Sequence[Shown], factor: float) -> list[Shown]:
    """``shown`` with every time multiplied by ``factor`` (planned → rendered length)."""
    return [
        Shown(item.text, item.look, round(item.start_ms * factor), round(item.end_ms * factor))
        for item in shown
    ]


# ── mp4: images for ffmpeg ────────────────────────────────────────────────────


@dataclass(frozen=True)
class OverlayImage:
    """A drawn overlay and where and when ffmpeg puts it."""

    path: Path
    x: str
    y: str
    start_ms: int
    end_ms: int


def margin_px(font_size: int) -> int:
    """Distance of an overlay from the picture's edge."""
    return font_size


def placement(position: str, margin: int) -> tuple[str, str]:
    """ffmpeg ``overlay`` expressions for ``position`` (W/H: picture, w/h: overlay)."""
    vertical = horizontal = "center"
    for part in position.split("-"):
        if part in ("top", "bottom"):
            vertical = part
        elif part in ("left", "right"):
            horizontal = part
    x = {"left": str(margin), "center": "(W-w)/2", "right": f"W-w-{margin}"}[horizontal]
    y = {"top": str(margin), "center": "(H-h)/2", "bottom": f"H-h-{margin}"}[vertical]
    return x, y


def _rgba(color: str) -> tuple[int, int, int, int]:
    value = color.removeprefix("#")
    alpha = int(value[6:8], 16) if len(value) == 8 else 255
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha


@functools.cache
def _font_file(bold: bool) -> str | None:
    fc_match = shutil.which("fc-match")
    if fc_match is None:
        return None
    pattern = "DejaVu Sans:bold" if bold else "DejaVu Sans"
    result = subprocess.run(  # noqa: S603
        [fc_match, "-f", "%{file}", pattern], capture_output=True, text=True, check=False
    )
    path = result.stdout.strip()
    return path if result.returncode == 0 and path.endswith((".ttf", ".otf")) else None


def _font(bold: bool, size: int) -> Any:
    from PIL import ImageFont

    path = _font_file(bold)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size)


def draw(text: str, look: Look, font_px: int, path: Path) -> Path:
    """Draw ``text`` into a transparent PNG at ``path``, in a box sized around it."""
    from PIL import Image, ImageDraw

    font = _font(look.bold, font_px)
    spacing = round(font_px * 0.3)
    stroke = 0 if look.box else max(2, round(font_px / 10))
    ascent, descent = font.getmetrics()
    lines = text.splitlines() or [text]
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    left, _, right, _ = probe.multiline_textbbox(
        (0, 0), text, font=font, spacing=spacing, stroke_width=stroke
    )
    pad_x, pad_y = (round(font_px * 0.7), round(font_px * 0.4)) if look.box else (stroke, stroke)
    text_h = len(lines) * (ascent + descent) + (len(lines) - 1) * spacing
    width, height = round(right - left) + 2 * pad_x, text_h + 2 * pad_y
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas = ImageDraw.Draw(image)
    if look.box:
        canvas.rounded_rectangle(
            (0, 0, width - 1, height - 1), radius=round(font_px * 0.45), fill=_rgba(look.background)
        )
    y = pad_y
    for line in lines:
        canvas.text(
            (pad_x - left, y),
            line,
            font=font,
            fill=_rgba(look.color),
            stroke_width=stroke,
            stroke_fill=(0, 0, 0, 220),
        )
        y += ascent + descent + spacing
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def images(spec: Spec, shown: Sequence[Shown], directory: Path) -> list[OverlayImage]:
    """Draw each overlay into ``directory`` and say where ffmpeg puts it."""
    font_size = spec.terminal.font_size
    result = []
    for number, item in enumerate(shown):
        png = draw(
            item.text, item.look, round(font_size * item.look.scale), directory / f"overlay-{number}.png"
        )
        x, y = placement(item.look.position, margin_px(font_size))
        result.append(OverlayImage(png, x, y, item.start_ms, item.end_ms))
    return result


def filter_graph(overlays: Sequence[OverlayImage], first_input: int, source: str) -> tuple[str, str]:
    """Filters laying ``overlays`` (inputs from ``first_input`` on) over ``source``.

    Returns the graph and the label of its output.
    """
    fade = FADE_MS / 1000
    parts, current = [], source
    for number, overlay in enumerate(overlays):
        start, end = overlay.start_ms / 1000, overlay.end_ms / 1000
        length = min(fade, (end - start) / 2)
        parts.append(
            f"[{first_input + number}:v]format=rgba,"
            f"fade=t=in:st={start:.3f}:d={length:.3f}:alpha=1,"
            f"fade=t=out:st={end - length:.3f}:d={length:.3f}:alpha=1[ov{number}]"
        )
        parts.append(
            f"[{current}][ov{number}]overlay=x={overlay.x}:y={overlay.y}:eof_action=pass[vo{number}]"
        )
        current = f"vo{number}"
    return ";".join(parts), current


# ── cast: HTML boxes ──────────────────────────────────────────────────────────


def page_overlays(shown: Sequence[Shown], terminal: Terminal) -> list[dict[str, Any]]:
    """The overlays as data for the cast page (times in seconds).

    ``size`` and ``margin`` are in percent of the player's width, matching the mp4.
    """
    from narratty.render.cast import CELL_WIDTH, terminal_size

    cols, _ = terminal_size(terminal)
    font = 100 / (cols * CELL_WIDTH)  # terminal.font_size in percent of the width
    return [
        {
            "text": item.text,
            "start": item.start_ms / 1000,
            "end": item.end_ms / 1000,
            "position": item.look.position,
            "size": round(font * item.look.scale, 3),
            "margin": round(font, 3),
            "color": item.look.color,
            "background": item.look.background if item.look.box else None,
            "bold": item.look.bold,
        }
        for item in shown
    ]
