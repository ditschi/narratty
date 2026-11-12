"""Browser views with a real Chromium."""

from __future__ import annotations

import base64
import shutil
from pathlib import Path

import pytest
from PIL import Image

from narratty.errors import MissingDependencyError, RenderError
from narratty.render import browser, slides
from narratty.spec.model import Slide

pytestmark = pytest.mark.integration

PAGE = """<!doctype html><html><body style="margin:0">
<div style="height:100vh;background:#ff0000"></div>
<div style="height:500px;background:#0000ff"></div>
</body></html>"""


@pytest.fixture
def chromium() -> str:
    try:
        return browser.find_chromium()
    except MissingDependencyError:
        if shutil.which("vhs"):
            raise
        pytest.skip("no Chromium")


@pytest.mark.parametrize(("scroll", "distance"), [("none", 0), (200, 200), ("auto", 500)])
def test_capture_scrolls_without_stretching_the_page(
    chromium: str, tmp_path: Path, scroll: str | int, distance: int
) -> None:
    page = tmp_path / "page.html"
    page.write_text(PAGE)
    shot = tmp_path / "shot.png"
    assert browser.capture(page.as_uri(), 400, 300, scroll, 5000, shot, chromium=chromium) == distance
    with Image.open(shot) as image:
        assert image.size == (400, 300 + distance)
        # 100vh stays the viewport's height although the image is taller.
        assert image.convert("RGB").getpixel((10, 290)) == (255, 0, 0)
        if distance:
            assert image.convert("RGB").getpixel((10, 300 + distance - 5)) == (0, 0, 255)


@pytest.fixture
def mermaid() -> None:
    try:
        browser.find_mermaid()
    except MissingDependencyError:
        pytest.skip("no mermaid.min.js")


def _diagram(source: str, tmp_path: Path) -> str:
    """A Mermaid slide as a data: URL (a snap Chromium cannot read files in /tmp)."""
    page = slides.page(Slide(mermaid=source), "dark", tmp_path)
    return "data:text/html;base64," + base64.b64encode(page.encode()).decode()


@pytest.mark.usefixtures("mermaid")
def test_capture_draws_mermaid_diagrams(chromium: str, tmp_path: Path) -> None:
    shot = tmp_path / "shot.png"
    browser.capture(
        _diagram("flowchart LR\n  a --> b\n", tmp_path), 400, 300, "none", 5000, shot, chromium=chromium
    )
    with Image.open(shot) as image:
        counts = {color: count for count, color in image.convert("RGB").getcolors(maxcolors=100_000) or []}
    assert counts.get((31, 32, 32), 0) > 1000, "the nodes are filled in the dark theme's colour"


@pytest.mark.usefixtures("mermaid")
def test_mermaid_errors_name_the_problem(chromium: str, tmp_path: Path) -> None:
    with pytest.raises(RenderError, match="Mermaid cannot draw a diagram: Parse error") as error:
        browser.capture(
            _diagram("flowchart LR\n  a -->\n", tmp_path),
            400,
            300,
            "none",
            5000,
            tmp_path / "x.png",
            chromium=chromium,
        )
    assert "    at " not in error.value.message
