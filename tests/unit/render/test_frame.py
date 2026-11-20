"""slides.frame: a band at the top that shows the heading over the terminal and slides alike."""

from __future__ import annotations

from pathlib import Path

from narratty.render import browser, slides
from narratty.render.overlays import frame_px, images, page_overlays, planned_times, resolve, schedule
from narratty.render.player import player_page
from narratty.render.script import build_script
from narratty.render.tape import generate_tape
from narratty.spec.loader import parse_spec
from narratty.spec.model import Overlay, Slide, Spec
from narratty.timeline import build_timeline

SPEC = """\
timing: {lead_in_ms: 100, tail_ms: 500, narration_buffer_ms: 0}
end_card: false
slides: {frame: true}
terminal: {font_size: 20}
scenes:
  - id: one
    narration: First.
    actions:
      - overlay: {text: Setup, style: heading-2}
      - slide: {title: Setup, points: [a, b]}
  - id: two
    narration: Second.
    actions:
      - slide: {title: Other, points: [c]}
"""


def _spec(text: str = SPEC) -> Spec:
    return parse_spec(text, Path("/tmp/t.narratty.yaml"))


def _times(spec: Spec) -> dict[str, int]:
    return planned_times(build_script(spec, build_timeline(spec, {"one": 1000, "two": 1000})))


def test_band_height_follows_the_font() -> None:
    assert frame_px(_spec()) == 52
    assert frame_px(_spec(SPEC.replace("font_size: 20", "font_size: 22"))) == 58, "even, for the encoder"
    assert frame_px(_spec(SPEC.replace("slides: {frame: true}", "slides: {frame: false}"))) == 0


def test_heading_overlays_move_into_the_frame_and_stay() -> None:
    spec = _spec()
    look = resolve(spec, Overlay(text="Setup", style="heading-2"))
    assert (look.position, look.keep, look.box, look.duration_ms) == ("frame", True, False, None)
    assert resolve(spec, Overlay(text="x", style="file")).position == "top", "other styles keep theirs"
    (item,) = schedule(spec, _times(spec))
    assert item.end_ms == _times(spec)["end"], "kept until the end, or the next heading"


def test_frame_text_sits_where_a_slide_title_starts(tmp_path: Path) -> None:
    spec = _spec()
    (image,) = images(spec, schedule(spec, _times(spec)), tmp_path)
    assert (image.x, image.y) == ("48", "(52-h)/2"), "51 of 1280 px at 1200 px wide; centred in the band"
    (data,) = page_overlays(schedule(spec, _times(spec)), spec.terminal, frame_px(spec))
    assert (data["position"], data["band"], data["margin"]) == ("frame", 4.333, 3.984)


def test_the_terminal_is_recorded_below_the_band() -> None:
    spec = _spec()
    tape = generate_tape(spec, build_timeline(spec, {"one": 1000, "two": 1000}), Path("/out/v.mp4"))
    assert "Set Height 648" in tape


def test_a_slide_titled_like_the_frame_drops_its_title() -> None:
    spec = _spec()
    times = _times(spec)
    first, second = browser.without_frame_titles(browser.schedule(spec, times), schedule(spec, times))
    assert first.slide is not None and first.slide.title is None
    assert second.slide is not None and second.slide.title == "Other"


def test_slides_leave_the_band_empty(tmp_path: Path) -> None:
    look = slides.look_of(_spec())
    assert (look.band, look.band_color) == (52, "#1e1f29")
    page = slides.page(Slide(points=["a"]), look, tmp_path)
    assert "margin:55px 0 0" in page, "52 video px at 1200 px wide, in the 1280 px layout"
    assert ":where(section.slide){background:#1e1f29;" in page, "dark slides take the terminal's background"


def test_cast_page_band(tmp_path: Path) -> None:
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"")
    page = player_page("T", "{}", audio, band={"height": 4.333, "color": "#282a36"})
    assert '<div id="band" style="height:4.333cqw;background:#282a36;"></div><div id="player">' in page
    assert "getComputedStyle" not in page
    unknown = player_page("T", "{}", audio, band={"height": 4.333, "color": None})
    assert '"#player .ap-player"' in unknown, "takes the player's background"


def test_cast_slides_sit_on_the_terminal_colour(tmp_path: Path) -> None:
    view = browser.View(None, 0, 1000, "one", Slide(points=["a"]))
    (tmp_path / "p.png").write_bytes(b"png")
    (data,) = browser.page_views([browser.Shot(view, None, tmp_path / "p.png", 700, 0)], _spec().terminal, 52)
    assert (data["background"], data["top"]) == ("#1e1f29", 0)
