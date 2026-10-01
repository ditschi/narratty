"""Text overlays: styles, timing, images and the ffmpeg filter graph."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from narratty.render.overlays import (
    OverlayImage,
    draw,
    filter_graph,
    page_overlays,
    placement,
    planned_times,
    resolve,
    schedule,
)
from narratty.render.script import build_script
from narratty.spec.loader import parse_spec
from narratty.spec.model import Overlay, Spec
from narratty.timeline import build_timeline

SPEC = """\
timing: {lead_in_ms: 100, tail_ms: 500, narration_buffer_ms: 0}
terminal: {typing_speed_ms: 10}
end_card: false
overlay_styles:
  file: {position: top, size: small}
scenes:
  - id: setup
    hidden: true
    actions: [{type_command: "true"}, enter]
  - id: one
    narration: First.
    actions:
      - overlay: {text: "1 · Setup", style: chapter}
      - type_command: ls
      - enter
      - overlay: Open main.py
      - overlay: {text: main.py, style: file, duration_ms: 200}
  - id: two
    narration: Second.
    actions:
      - hold: 300
      - overlay: Build
      - overlay: {text: "2 · Build", style: chapter}
"""


def _spec(text: str = SPEC, tmp_path: Path = Path("/tmp")) -> Spec:
    return parse_spec(text, tmp_path / "t.narratty.yaml")


def test_styles_layer_from_builtin_to_overlay() -> None:
    spec = Spec.model_validate(
        {
            "overlay_styles": {"default": {"color": "#ff0000"}, "chapter": {"size": 2}},
            "scenes": [{"id": "a", "actions": [{"overlay": "x"}]}],
        }
    )
    plain = resolve(spec, Overlay(text="x"))
    assert (plain.position, plain.color, plain.box, plain.keep) == ("bottom-right", "#ff0000", True, False)
    chapter = resolve(spec, Overlay(text="x", style="chapter", box=False))
    assert (chapter.position, chapter.scale, chapter.bold, chapter.keep) == ("top-right", 2.0, True, True)
    assert (chapter.color, chapter.box) == ("#ff0000", False)


def test_text_shorthand_and_unknown_style() -> None:
    spec = Spec.model_validate({"scenes": [{"id": "a", "actions": [{"overlay": "Hi"}]}]})
    assert spec.scenes[0].actions[0].overlay.text == "Hi"  # type: ignore[union-attr]
    with pytest.raises(ValidationError, match="unknown overlay style 'nope'"):
        Spec.model_validate(
            {"scenes": [{"id": "a", "actions": [{"overlay": {"text": "x", "style": "nope"}}]}]}
        )
    with pytest.raises(ValidationError, match="hidden scene cannot show an overlay"):
        Spec.model_validate({"scenes": [{"id": "a", "hidden": True, "actions": [{"overlay": "x"}]}]})
    with pytest.raises(ValidationError, match="color"):
        Spec.model_validate(
            {"scenes": [{"id": "a", "actions": [{"overlay": {"text": "x", "color": "red"}}]}]}
        )


def test_planned_times_match_the_timeline() -> None:
    spec = _spec()
    timeline = build_timeline(spec, {"one": 1000, "two": 1000})
    times = planned_times(build_script(spec, timeline))
    assert times["one"] == timeline.scene("one").start_ms == 100
    assert times["overlay:one:3"] == 100 + 2 * 10 + 10 + 100  # after typing "ls", Enter and its pause
    assert times["two"] == timeline.scene("two").start_ms
    assert times["overlay:two:1"] == times["two"] + 300
    assert times["end"] == timeline.total_ms - 500


def test_schedule_ends_at_scene_duration_replacement_or_end() -> None:
    spec = _spec()
    times = planned_times(build_script(spec, build_timeline(spec, {"one": 1000, "two": 1000})))
    shown = {item.text: (item.start_ms, item.end_ms) for item in schedule(spec, times)}
    two, end = times["two"], times["end"]
    assert shown["1 · Setup"] == (100, two + 300)  # kept until the next chapter takes its place
    assert shown["Open main.py"] == (230, two)  # ends with its scene
    assert shown["main.py"] == (230, 430)  # duration_ms
    assert shown["Build"] == (two + 300, end)
    assert shown["2 · Build"] == (two + 300, end)


def test_placement() -> None:
    assert placement("top-left", 20) == ("20", "20")
    assert placement("bottom", 20) == ("(W-w)/2", "H-h-20")
    assert placement("right", 20) == ("W-w-20", "(H-h)/2")
    assert placement("center", 20) == ("(W-w)/2", "(H-h)/2")


def test_draw_sizes_the_box_around_the_text(tmp_path: Path) -> None:
    from PIL import Image

    look = resolve(_spec(), Overlay(text="x"))
    short = Image.open(draw("ab", look, 28, tmp_path / "a.png"))
    long = Image.open(draw("a much longer line", look, 28, tmp_path / "b.png"))
    two = Image.open(draw("two\nlines", look, 28, tmp_path / "c.png"))
    assert long.width > short.width
    assert two.height > short.height
    assert short.mode == "RGBA"
    assert short.getpixel((0, 0))[3] == 0  # rounded corner
    assert short.getpixel((short.width // 2, 2))[3] == 0xB3  # box at the default alpha


def test_filter_graph_fades_each_overlay() -> None:
    overlays = [
        OverlayImage(Path("a.png"), "10", "10", 1000, 3000),
        OverlayImage(Path("b.png"), "1", "1", 0, 100),
    ]
    graph, out = filter_graph(overlays, 2, "0:v")
    assert out == "vo1"
    assert "[2:v]format=rgba,fade=t=in:st=1.000:d=0.200:alpha=1,fade=t=out:st=2.800" in graph
    assert "[0:v][ov0]overlay=x=10:y=10:eof_action=pass[vo0]" in graph
    assert "fade=t=in:st=0.000:d=0.050" in graph  # short overlays fade quicker


def test_page_overlays(tmp_path: Path) -> None:
    spec = _spec()
    times = planned_times(build_script(spec, build_timeline(spec, {"one": 1000, "two": 1000})))
    data = page_overlays(schedule(spec, times), spec.terminal)
    chapter = data[0]
    assert (chapter["text"], chapter["start"], chapter["position"], chapter["bold"]) == (
        "1 · Setup",
        0.1,
        "top-right",
        True,
    )
    assert chapter["background"] == "#000000b3"
    assert 0 < chapter["size"] < 10
