"""Browser views with a real Chromium."""

from __future__ import annotations

import base64
import os
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


def test_capture_draws_highlighted_code_slides(chromium: str, tmp_path: Path) -> None:
    page = slides.page(Slide(code='{\n  "status": "ok"\n}', lang="json", title="Response"), "dark", tmp_path)
    shot = tmp_path / "code.png"
    browser.capture(
        "data:text/html;base64," + base64.b64encode(page.encode()).decode(),
        600,
        400,
        "none",
        5000,
        shot,
        chromium=chromium,
    )
    with Image.open(shot) as image:
        rgb = image.convert("RGB")
        pink = [
            (x, y)
            for x in range(0, rgb.width, 2)
            for y in range(0, rgb.height, 2)
            if rgb.getpixel((x, y)) == (255, 121, 198)
        ]
    assert pink, "the JSON key is drawn in the Dracula key colour"
    assert min(y for _, y in pink) > 60, "below the title"


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
def test_capture_focuses_mermaid_node(chromium: str, tmp_path: Path) -> None:
    page = slides.page(
        Slide(mermaid='flowchart LR\n  api["🚀 API"] --> db[Database]', focus="db"), "dark", tmp_path
    )
    shot = tmp_path / "focused.png"
    browser.capture(
        "data:text/html;base64," + base64.b64encode(page.encode()).decode(),
        600,
        400,
        "none",
        5000,
        shot,
        chromium=chromium,
    )
    with Image.open(shot) as image:
        colors = {color: count for count, color in image.convert("RGB").getcolors(maxcolors=100_000) or []}
    assert colors.get((189, 147, 249), 0) > 0, "the focused node uses the slide accent"


ACCENT = (189, 147, 249)  # the dark slide theme's accent, used for the focus outline


def _accent_span(source: str, focus: str, chromium: str, tmp_path: Path) -> tuple[int, int]:
    """Leftmost and rightmost x of the focus outline on a 600 px wide slide."""
    page = slides.page(Slide(mermaid=source, focus=focus), "dark", tmp_path)
    shot = tmp_path / "focused.png"
    browser.capture(
        "data:text/html;base64," + base64.b64encode(page.encode()).decode(),
        600,
        400,
        "none",
        5000,
        shot,
        chromium=chromium,
    )
    with Image.open(shot) as image:
        rgb = image.convert("RGB")
        xs = [x for x in range(rgb.width) for y in range(0, rgb.height, 2) if rgb.getpixel((x, y)) == ACCENT]
    assert xs, f"{focus} is outlined in the slide accent"
    return min(xs), max(xs)


@pytest.mark.usefixtures("mermaid")
def test_focus_picks_the_exact_node_not_one_whose_id_it_begins(chromium: str, tmp_path: Path) -> None:
    source = "flowchart LR\n  api-gateway --> api\n"
    gateway = _accent_span(source, "api-gateway", chromium, tmp_path)
    api = _accent_span(source, "api", chromium, tmp_path)
    assert gateway[1] < api[0], "api is the node on the right, not api-gateway"


@pytest.mark.usefixtures("mermaid")
def test_focus_outlines_nested_shapes(chromium: str, tmp_path: Path) -> None:
    # Mermaid 11 draws a cylinder as a path, a stadium inside a <g class="label-container">.
    api = _accent_span("flowchart LR\n  api --> db[(db)]\n", "api", chromium, tmp_path)
    db = _accent_span("flowchart LR\n  api --> db[(db)]\n", "db", chromium, tmp_path)
    assert api[1] < db[0]
    source = "flowchart LR\n  api --> s@{ shape: stadium, label: Queue }\n"
    assert (
        _accent_span(source, "api", chromium, tmp_path)[1] < _accent_span(source, "s", chromium, tmp_path)[0]
    )


@pytest.mark.usefixtures("mermaid")
def test_focus_takes_subgraphs_and_ids_with_dashes_and_digits(chromium: str, tmp_path: Path) -> None:
    source = "flowchart LR\n  n1-2 --> n1\n  subgraph back-end-2\n    n1\n  end\n"
    first = _accent_span(source, "n1-2", chromium, tmp_path)
    node = _accent_span(source, "n1", chromium, tmp_path)
    group = _accent_span(source, "back-end-2", chromium, tmp_path)
    assert first[1] < node[0]
    assert group[0] < node[0] and group[1] > node[1], "the subgraph's box around n1"


@pytest.mark.usefixtures("mermaid")
def test_focus_on_a_missing_id_lists_the_rendered_ones(chromium: str, tmp_path: Path) -> None:
    page = slides.page(
        Slide(mermaid="flowchart LR\n  api-gateway --> api\n", focus="gateway"), "dark", tmp_path
    )
    with pytest.raises(
        RenderError,
        match=r"no Mermaid node or subgraph with id gateway \(rendered ids: "
        r"api-gateway, api\)",
    ):
        browser.capture(
            "data:text/html;base64," + base64.b64encode(page.encode()).decode(),
            400,
            300,
            "none",
            5000,
            tmp_path / "x.png",
            chromium=chromium,
        )


@pytest.mark.usefixtures("mermaid")
def test_capture_draws_fontawesome_icons_offline(chromium: str, tmp_path: Path) -> None:
    pack = os.environ.get(browser.FONTAWESOME_ENV)
    if not pack or not Path(pack).is_file():
        pytest.skip("no local Font Awesome Iconify pack")
    page = slides.page(
        Slide(mermaid='flowchart LR\n  server@{ icon: "fa:server", label: "Server", form: "square" }'),
        "dark",
        tmp_path,
    )
    browser.capture(
        "data:text/html;base64," + base64.b64encode(page.encode()).decode(),
        600,
        400,
        "none",
        5000,
        tmp_path / "fontawesome.png",
        chromium=chromium,
    )


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
