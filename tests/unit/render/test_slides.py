"""Slides: the action, its checks, the generated page and how it is shown."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from narratty.errors import RenderError
from narratty.render import browser, slides
from narratty.render.overlays import planned_times
from narratty.render.script import build_script
from narratty.spec.loader import parse_spec
from narratty.spec.model import Slide
from narratty.timeline import build_timeline

TABLE = {"header": ["Hazard", "Fix"], "rows": [[f"h{n}", f"`f{n}` <b>x</b>"] for n in range(1, 6)]}


def _slide(**keys: object) -> Slide:
    return Slide.model_validate(keys)


@pytest.mark.parametrize(
    ("keys", "message"),
    [
        ({}, "exactly one of: table, mermaid, image, html"),
        ({"mermaid": "graph TD", "image": "a.png"}, "exactly one of"),
        ({"mermaid": "graph TD", "highlight": 1}, "only apply to table slides"),
        ({"table": TABLE, "focus": "api"}, "focus only applies to Mermaid slides"),
        ({"table": TABLE, "highlight": 6}, "highlight 6: the table has 5 rows"),
        ({"table": TABLE, "rows": 2, "page": 4}, r"page 4: the table has 3 page\(s\)"),
        ({"html": "a.html", "title": "A"}, "title and theme do not apply"),
        ({"html": "https://example.com"}, "browser action"),
        ({"image": "notes.pdf"}, "not .pdf"),
    ],
)
def test_slide_checks(keys: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _slide(**keys)


def test_highlight_picks_the_page() -> None:
    assert _slide(table=TABLE, rows=2, highlight=3).shown_page == 2
    assert _slide(table=TABLE, rows=2, highlight=3, page=1).shown_page == 1
    assert _slide(table=TABLE, highlight=5).shown_page == 1


def test_table_page(tmp_path: Path) -> None:
    page = slides.page(_slide(title="Risks", table=TABLE, rows=2, highlight=3), "dark", tmp_path)
    assert "<header>Risks</header>" in page
    assert "<th>Hazard</th>" in page
    assert '<tr class="mark"><td>h3</td><td><code>f3</code> &lt;b&gt;x&lt;/b&gt;</td></tr>' in page
    assert "h2" not in page and "h5" not in page, "only the rows of page 2"
    assert "<footer>2/3</footer>" in page
    assert "#282a36" in page, "dark by default"


def test_light_theme_and_mermaid(tmp_path: Path) -> None:
    page = slides.page(_slide(mermaid="graph TD\n  a --> b", theme="light"), "dark", tmp_path)
    assert '<pre class="mermaid">graph TD\n  a --&gt; b</pre>' in page
    assert 'data-mermaid-theme="default"' in page
    assert "#ffffff" in page
    assert 'data-mermaid-theme="dark"' in slides.page(_slide(mermaid="graph TD"), "dark", tmp_path)


def test_mermaid_focus_is_carried_to_the_rendered_page(tmp_path: Path) -> None:
    page = slides.page(_slide(mermaid="flowchart LR\n  api --> db", focus="api"), "dark", tmp_path)
    assert '<body data-mermaid-theme="dark" data-mermaid-focus="api">' in page
    assert ".narratty-focus" in page
    # Mermaid 11 nests some shapes (cylinder, stadium) in a label-container group; labels stay as they are.
    assert ".narratty-focus :is(.label-container,.label-container *)" in page


def test_image_from_the_workspace(tmp_path: Path) -> None:
    (tmp_path / "pic.png").write_bytes(b"png")
    page = slides.page(_slide(image="pic.png"), "dark", tmp_path)
    assert f'src="{(tmp_path / "pic.png").as_uri()}"' in page
    with pytest.raises(RenderError, match="missing.png is not a file in the workspace"):
        slides.page(_slide(image="missing.png"), "dark", tmp_path)


def test_image_outside_the_workspace_is_refused(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "secret.png").write_bytes(b"png")
    for image in ("../secret.png", str(tmp_path / "secret.png")):
        with pytest.raises(RenderError, match="is outside the workspace"):
            slides.page(_slide(image=image), "dark", workspace)


SPEC = """\
timing: {lead_in_ms: 100, tail_ms: 500, narration_buffer_ms: 0}
terminal: {typing_speed_ms: 10}
end_card: false
scenes:
  - id: one
    narration: First.
    actions:
      - browser: https://github.com/ditschi/narratty
      - hold: 200
      - slide: {mermaid: "graph TD", duration_ms: 300}
  - id: two
    narration: Second.
    actions:
      - slide: {image: docs/a.png}
"""


def test_slides_are_scheduled_like_browser_views() -> None:
    spec = parse_spec(SPEC, Path("/tmp/t.narratty.yaml"))
    times = planned_times(build_script(spec, build_timeline(spec, {"one": 1000, "two": 1000})))
    page, diagram, image = browser.schedule(spec, times)
    assert page.browser is not None and page.slide is None
    assert page.end_ms == diagram.start_ms, "the slide replaces the page"
    assert diagram.slide is not None and diagram.end_ms == diagram.start_ms + 300
    assert image.slide is not None and image.scene_id == "two"


def test_a_hidden_scene_cannot_show_a_slide() -> None:
    with pytest.raises(Exception, match="hidden scene cannot show a slide"):
        parse_spec(
            "scenes:\n  - id: a\n    hidden: true\n    actions: [{slide: {mermaid: x}}]\n",
            Path("/tmp/t.yaml"),
        )


def test_slides_have_no_bar(tmp_path: Path) -> None:
    view = browser.View(None, 1000, 3000, "one", _slide(mermaid="graph TD"))
    shot = browser.Shot(view, None, tmp_path / "page.png", view_px=720, scroll_px=0)
    (page,) = browser.images([shot], bar_px=40)
    assert (page.y, page.view_px) == ("0", 720)
    (tmp_path / "page.png").write_bytes(b"png")
    spec = parse_spec(SPEC, Path("/tmp/t.narratty.yaml"))
    (data,) = browser.page_views([shot], spec.terminal)
    assert data["bar"] is None and data["bar_height"] == 0
