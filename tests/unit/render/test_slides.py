"""Slides: the action, its checks, the generated page and how it is shown."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from narratty.errors import RenderError
from narratty.render import browser, slides
from narratty.render.overlays import planned_times
from narratty.render.script import build_script
from narratty.spec.loader import SpecError, parse_document, parse_spec
from narratty.spec.model import Slide
from narratty.timeline import build_timeline

TABLE = {"header": ["Hazard", "Fix"], "rows": [[f"h{n}", f"`f{n}` <b>x</b>"] for n in range(1, 6)]}


def _slide(**keys: object) -> Slide:
    return Slide.model_validate(keys)


@pytest.mark.parametrize(
    ("keys", "message"),
    [
        ({}, "exactly one of: table, mermaid, image, html, code, points"),
        ({"mermaid": "graph TD", "lang": "json"}, "lang only applies to code slides"),
        ({"code": "x", "lang": "a b"}, "lang"),
        ({"mermaid": "graph TD", "image": "a.png"}, "exactly one of"),
        ({"mermaid": "graph TD", "highlight": 1}, "only apply to table slides"),
        ({"table": TABLE, "focus": "api"}, "focus only applies to Mermaid slides"),
        ({"table": TABLE, "highlight": 6}, "highlight 6: the table has 5 rows"),
        ({"table": TABLE, "rows": 2, "page": 4}, r"page 4: the table has 3 page\(s\)"),
        ({"html": "a.html", "title": "A"}, "title and theme do not apply"),
        ({"html": "https://example.com"}, "browser action"),
        ({"image": "notes.pdf"}, "not .pdf"),
        ({"table": {"header": ["A", "B"], "rows": [["1", "2"], ["3"]]}}, "row 2 has 1 cell.*header has 2"),
        ({"table": {"header": ["A"], "rows": [["1", "2"]]}}, "row 1 has 2 cell.*header has 1"),
        ({"table": {"rows": [["1", "2"], ["3", "4", "5"]]}}, "row 2 has 3 cell.*row 1 has 2"),
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
    assert "<h1>Risks</h1>" in page
    assert "<th>Hazard</th>" in page
    assert '<tr class="mark"><td>h3</td><td><code>f3</code> &lt;b&gt;x&lt;/b&gt;</td></tr>' in page
    assert "h2" not in page and "h5" not in page, "only the rows of page 2"
    assert "<footer>2/3</footer>" in page
    assert "#282a36" in page, "dark by default"


def test_light_theme_and_mermaid(tmp_path: Path) -> None:
    page = slides.page(_slide(mermaid="graph TD\n  a --> b", theme="light"), "dark", tmp_path)
    assert '<div class="mermaid">graph TD\n  a --&gt; b</div>' in page
    assert 'data-mermaid-theme="default"' in page
    assert "#ffffff" in page
    assert 'data-mermaid-theme="dark"' in slides.page(_slide(mermaid="graph TD"), "dark", tmp_path)


def test_mermaid_focus_is_carried_to_the_rendered_page(tmp_path: Path) -> None:
    page = slides.page(_slide(mermaid="flowchart LR\n  api --> db", focus="api"), "dark", tmp_path)
    assert '<body data-mermaid-theme="dark" data-mermaid-focus="api">' in page
    assert ".narratty-focus" in page
    # Mermaid 11 nests some shapes (cylinder, stadium) in a label-container group; labels stay as they are.
    assert ".narratty-focus :is(.label-container,.label-container *)" in page


def test_code_is_highlighted(tmp_path: Path) -> None:
    page = slides.page(_slide(code='{"status": "ok"}', lang="json", title="Response"), "dark", tmp_path)
    assert '<pre class="code" style="font-size:30.72px"><code>' in page
    assert '<span style="color: #FF79C6">"status"</span>' in page, "dracula colours"
    assert "<h1>Response</h1>" in page
    assert "code,pre{font-variant-ligatures:none}" in page, "-> stays two characters, not an arrow"
    light = slides.page(_slide(code="<b>&</b>", lang="no-such-language", theme="light"), "dark", tmp_path)
    assert "&lt;b&gt;&amp;&lt;/b&gt;" in light, "unknown languages are plain text"


def test_points_mark_the_current_one(tmp_path: Path) -> None:
    page = slides.page(
        _slide(points=["First `one`", "Second", "Third"], current=2, title="Steps"), "dark", tmp_path
    )
    assert '<li class="done">First <code>one</code></li>' in page
    assert '<li class="current">Second</li>' in page
    assert '<li class="next">Third</li>' in page
    plain = slides.page(_slide(points=["Only"]), "dark", tmp_path)
    assert "<li>Only</li>" in plain, "nothing marked without current"


def test_current_needs_points_within_range() -> None:
    with pytest.raises(ValueError, match="current only applies to points slides"):
        _slide(code="x", current=1)
    with pytest.raises(ValueError, match="current 3: there are 2 points"):
        _slide(points=["a", "b"], current=3)


def test_a_css_file_comes_after_the_built_in_look(tmp_path: Path) -> None:
    look = slides.Look(width=1920, height=1080, css="section{background:#455a64}", classes="invert lead")
    page = slides.page(_slide(points=["A"], title="T"), look, tmp_path)
    assert page.index(":where(section.slide)") < page.index("section{background:#455a64}")
    assert '<section class="slide points invert lead"><h1>T</h1><div class="content">' in page
    assert "html{zoom:1.500000}" in page, "laid out 1280 px wide, zoomed to the video"
    assert "font-weight:bold;\ncolor:inherit}" in page, "the title takes the theme's colour"
    assert "section.slide pre.code{background:#282a36;color:#f8f8f2;" in page, "code stays readable"
    assert "color:inherit;\npadding:0;margin:0;background:transparent}" in page, "also its plain text"
    assert "section.slide{width:1280px;height:720px;" in page
    assert "display:flex;align-items:center;justify-content:center;" in page, (
        "centred, not stretched, under a theme"
    )


def test_look_of_the_spec(tmp_path: Path) -> None:
    (tmp_path / "theme.css").write_text("h1{color:red}")
    spec = parse_document(
        "slides: {css: theme.css, classes: invert}\n"
        "terminal: {theme: {background: '#101010'}}\n"
        "scenes: [{id: a}]\n",
        tmp_path / "t.narratty.yaml",
    ).spec
    assert spec.slides.css is not None and spec.slides.css.startswith("data:text/css;base64,")
    look = slides.look_of(spec)
    assert (look.css, look.classes, look.band_color) == ("h1{color:red}", "invert", "#101010")
    assert slides.look_of(parse_spec("scenes: [{id: a}]\n", tmp_path / "u.yaml")).band_color == "#1e1f29"


def test_a_missing_css_file_is_reported_at_its_key(tmp_path: Path) -> None:
    with pytest.raises(SpecError, match="cannot read missing.css") as error:
        parse_document("slides:\n  css: missing.css\nscenes: [{id: a}]\n", tmp_path / "t.narratty.yaml")
    assert error.value.issues[0].line == 2


def test_long_code_gets_smaller(tmp_path: Path) -> None:
    page = slides.page(_slide(code="\n".join(["x" * 120] * 3)), "dark", tmp_path)
    assert 'style="font-size:15.11px"' in page


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


def test_a_container_gets_the_css_embedded_in_its_compiled_spec(tmp_path: Path) -> None:
    from narratty.spec.compile import container_spec

    (tmp_path / "theme.css").write_text("h1{color:red}")
    spec = tmp_path / "t.narratty.yaml"
    spec.write_text("slides: {css: theme.css}\nscenes: [{id: a, narration: Hi.}]\n")
    compiled = container_spec(spec, tmp_path / "cache")
    assert compiled is not None, "compiled although it has no Markdown"
    text = compiled.read_text()
    assert "data:text/css;base64," in text and "theme.css" not in text
    assert parse_document(text, tmp_path / "elsewhere" / "t.narratty.yaml").spec.slides.css == (
        parse_document(spec.read_text(), spec).spec.slides.css
    ), "it loads without the file"
    plain = tmp_path / "plain.narratty.yaml"
    plain.write_text("scenes: [{id: a, narration: Hi.}]\n")
    assert container_spec(plain, tmp_path / "cache") is None


def test_mermaid_is_not_run_on_the_slide_section(tmp_path: Path) -> None:
    page = slides.page(_slide(mermaid="graph TD", title="Flow"), "dark", tmp_path)
    assert '<section class="slide mermaid">' in page, "the section carries the kind as a class"
    for script in (browser.NEEDS_MERMAID_JS, browser.NEEDS_FONTAWESOME, browser.RUN_MERMAID_JS):
        assert "'.mermaid:not(section)'" in script and "'.mermaid'" not in script
