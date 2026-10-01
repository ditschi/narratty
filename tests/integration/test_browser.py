"""Browser views with a real Chromium."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image

from narratty.errors import MissingDependencyError
from narratty.render import browser

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
