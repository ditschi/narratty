"""Browser views: the action, timing, URLs, images and the cast page data."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from narratty.errors import MissingDependencyError, RenderError
from narratty.render import browser
from narratty.render.overlays import filter_graph, planned_times
from narratty.render.script import build_script
from narratty.spec.loader import parse_spec
from narratty.spec.model import Spec
from narratty.timeline import build_timeline

SPEC = """\
timing: {lead_in_ms: 100, tail_ms: 500, narration_buffer_ms: 0}
terminal: {typing_speed_ms: 10}
end_card: false
scenes:
  - id: one
    narration: First.
    actions:
      - type_command: ls
      - enter
      - browser: https://github.com/ditschi/narratty
  - id: two
    narration: Second.
    actions:
      - browser: {url: site/index.html, scroll: auto, duration_ms: 200}
      - hold: 300
      - browser: {url: site/other.html, scroll: 120}
"""


def _spec(text: str = SPEC) -> Spec:
    return parse_spec(text, Path("/tmp/t.narratty.yaml"))


def _times(spec: Spec) -> dict[str, int]:
    timeline = build_timeline(spec, {"one": 1000, "two": 1000})
    return planned_times(build_script(spec, timeline))


def test_shorthand_and_defaults() -> None:
    action = _spec().scenes[0].actions[2]
    assert isinstance(action, browser.ShowBrowser)
    assert action.browser.url == "https://github.com/ditschi/narratty"
    assert action.browser.scroll == "none"
    assert action.browser.duration_ms is None


def test_hidden_scene_cannot_show_a_browser() -> None:
    with pytest.raises(Exception, match="hidden scene cannot show a browser"):
        Spec.model_validate({"scenes": [{"id": "a", "hidden": True, "actions": [{"browser": "x.html"}]}]})


def test_schedule_until_scene_end_duration_or_next_view() -> None:
    spec = _spec()
    times = _times(spec)
    views = browser.schedule(spec, times)
    assert [v.browser.url for v in views] == [
        "https://github.com/ditschi/narratty",
        "site/index.html",
        "site/other.html",
    ]
    first, second, third = views
    assert (first.start_ms, first.end_ms) == (times["overlay:one:2"], times["two"])
    assert second.end_ms == second.start_ms + 200
    assert third.start_ms == second.start_ms + 300
    assert third.end_ms == times["end"]


def test_page_url(tmp_path: Path) -> None:
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "index.html").write_text("<h1>hi</h1>")
    assert browser.page_url("https://example.org", tmp_path) == "https://example.org"
    assert browser.page_url("site/index.html", tmp_path) == (tmp_path / "site/index.html").as_uri()
    with pytest.raises(RenderError, match="not a file"):
        browser.page_url("site/missing.html", tmp_path)


def test_web_pages_need_network_in_the_container(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec()
    monkeypatch.setenv("NARRATTY_IN_CONTAINER", "1")
    with pytest.raises(RenderError, match="needs network access") as error:
        browser.check_network(spec, "https://github.com")
    assert error.value.hint is not None and "network: full" in error.value.hint
    browser.check_network(spec, "file:///work/site/index.html")
    monkeypatch.delenv("NARRATTY_IN_CONTAINER")
    browser.check_network(spec, "https://github.com")


def test_find_chromium_reports_a_missing_browser(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(MissingDependencyError, match="Chromium"):
        browser.find_chromium()


def test_scrolling_page_and_bar_as_ffmpeg_inputs(tmp_path: Path) -> None:
    view = browser.View(browser.Browser(url="x.html", scroll="auto"), 1000, 7000)
    shot = browser.Shot(view, tmp_path / "bar.png", tmp_path / "page.png", view_px=600, scroll_px=900)
    assert shot.scroll_ms == (2000, 6000)
    page, bar = browser.images([shot], bar_px=40)
    assert (page.y, page.view_px, page.scroll_px) == ("40", 600, 900)
    assert (bar.y, bar.view_px) == ("0", 0)
    graph, _ = filter_graph([page, bar], 2, "0:v")
    assert "crop=w=iw:h=600:x=0:y='900*clip((t-2.000)/4.000,0,1)'" in graph
    assert graph.count("crop=") == 1


def test_short_views_pause_less() -> None:
    view = browser.View(browser.Browser(url="x.html"), 0, 2000)
    assert browser.Shot(view, Path(), Path(), 600, 0).scroll_ms == (500, 1500)


def test_bar_shows_the_address(tmp_path: Path) -> None:
    path = browser.draw_bar("https://github.com/ditschi/narratty", 800, 40, tmp_path / "bar.png")
    with Image.open(path) as image:
        assert image.size == (800, 40)


def test_page_views_for_the_cast_page(tmp_path: Path) -> None:
    spec = _spec()
    Image.new("RGB", (10, 10)).save(tmp_path / "p.png")
    view = browser.View(browser.Browser(url="x.html"), 1000, 5000)
    shot = browser.Shot(view, tmp_path / "p.png", tmp_path / "p.png", view_px=660, scroll_px=1200)
    (data,) = browser.page_views([shot], spec.terminal)
    assert data["start"] == 1.0 and data["end"] == 5.0
    assert data["scroll"] == [2.0, 4.0]
    assert data["scroll_by"] == 100.0  # 1200 px of a 1200 px wide video
    assert str(data["page"]).startswith("data:image/png;base64,")
