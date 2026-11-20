"""Slides: a table, Mermaid diagram, image or code on a full-screen page.

Each slide becomes an HTML file that :mod:`.browser` captures like a browser view, but
without the address bar. Loaded from a file, the page can show workspace images and
embedded ones of any size. Mermaid diagrams are drawn during the capture.
"""

from __future__ import annotations

import base64
import html
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from markdown_it import MarkdownIt

from narratty.errors import RenderError
from narratty.render.overlays import frame_px
from narratty.spec.model import Slide, SlideTable, SlideTheme, Spec

COLORS = {
    "dark": {
        "bg": "#282a36",
        "fg": "#f8f8f2",
        "accent": "#bd93f9",
        "line": "#44475a",
        "mark": "#44475a",
        "code": "#50fa7b",
        "link": "#8be9fd",
    },
    "light": {
        "bg": "#ffffff",
        "fg": "#282a36",
        "accent": "#6c4ab6",
        "line": "#d0d0da",
        "mark": "#ece6fb",
        "code": "#1a7f37",
        "link": "#0969da",
    },
}
MERMAID_THEMES = {"dark": "dark", "light": "default"}
CODE_STYLES = {"dark": "dracula", "light": "default"}  # Pygments styles

DESIGN_WIDTH = 1280
"""Slides are laid out this many CSS pixels wide (as Marp themes are) and zoomed to the video."""

# Layout every slide needs, also under a theme from ``slides.css``.
_LAYOUT = """
html{{zoom:{zoom}}}
html,body{{margin:0;padding:0;overflow:hidden;background:{band_color}}}
section.slide{{width:1280px;height:{section_height}px;box-sizing:border-box;display:flex;flex-direction:column;
overflow:hidden;position:relative;margin:{band}px 0 0}}
section.slide>.content{{flex:1;min-height:0;display:flex;align-items:center;justify-content:center;
overflow:hidden}}
:where(section.slide>.content>*){{margin:auto}}
section.slide>footer{{position:absolute;right:26px;bottom:10px}}
code,pre{{font-variant-ligatures:none}}
.content img{{max-width:1203px;max-height:100%;object-fit:contain}}
pre.mermaid svg{{max-width:100%!important;max-height:{diagram_height}px;height:auto}}
"""
# The built-in look; :where() keeps it below any rule of a slides.css.
_LOOK = """
:where(section.slide){{background:{bg};color:{fg};font-family:'DejaVu Sans','Noto Color Emoji',sans-serif}}
:where(section.slide>h1){{margin:0;padding:{title_pad}px 51px 0;font-size:41px;font-weight:bold;
color:{accent}}}
:where(section.slide>footer){{font-size:20px;opacity:.7}}
:where(table){{border-collapse:collapse;max-width:1203px;font-size:28px}}
:where(th,td){{padding:.45em .8em;border-bottom:1px solid {line};text-align:left}}
:where(th){{color:{accent}}}
:where(tr.mark){{background:{mark};outline:3px solid {accent}}}
:where(code){{font-family:'JetBrains Mono',monospace;color:{code}}}
:where(a){{color:{link}}}
:where(pre.mermaid){{width:1203px;text-align:center;font:20px 'JetBrains Mono',monospace;
white-space:pre-wrap}}
:where(pre.code){{max-width:1178px;padding:{code_pad}px 32px;border:1px solid {line};
border-radius:8px;overflow:hidden;
font-family:'JetBrains Mono','DejaVu Sans Mono',monospace;line-height:1.35}}
:where(pre.code code){{color:{fg};font-family:inherit}}
:where(ul.points){{list-style:none;margin:{points_top}px 0 0;padding:0 64px;width:1152px;
font-size:32px;line-height:1.35;
align-self:flex-start}}
:where(ul.points li){{margin:0 0 {gap}px;padding:{item_pad}px 20px;
border-left:6px solid transparent;border-radius:6px}}
:where(ul.points li.current){{border-left-color:{accent};background:{mark}}}
.narratty-focus>:is(rect,polygon,circle,path,line),
.narratty-focus :is(.label-container,.label-container *){{stroke:{accent}!important;
stroke-width:4px!important;filter:drop-shadow(0 0 5px {accent})}}
"""
# Marks the current point under any theme: the others are dimmed.
_STATES = """
:where(ul.points li.done){opacity:.6}
:where(ul.points li.next){opacity:.35}
"""
# A table taller than the slide moves up until the highlighted row is in the middle.
_FOLLOW_MARK = (
    "const m=document.querySelector('.content'),t=m.querySelector('table'),r=t.querySelector('tr.mark'),"
    "h=m.clientHeight;if(r&&t.offsetHeight>h){const y=Math.min(Math.max(r.offsetTop+r.offsetHeight/2-h/2,0),"
    "t.offsetHeight-h);t.style.transform='translateY('+(-y)+'px)'}"
)
_INLINE = MarkdownIt("commonmark", {"html": False}).disable("image")


@dataclass(frozen=True)
class Look:
    """How slides look: the built-in theme, the video size, and an optional ``slides.css``."""

    theme: SlideTheme = "dark"
    width: int = 1200
    height: int = 700
    css: str = ""
    classes: str = ""
    band: int = 0
    """Height of the frame at the top, in video pixels (``slides.frame``); the slide is below it."""
    band_color: str | None = None
    """Colour of the frame: the terminal's background; unset: the slide background."""
    background: str | None = None
    """Background of dark slides: the terminal's, when known, so both look alike."""

    @property
    def design_height(self) -> int:
        return round(DESIGN_WIDTH * self.height / self.width)

    def design_px(self, video_px: int) -> int:
        return round(video_px * DESIGN_WIDTH / self.width)


def look_of(spec: Spec) -> Look:
    """The slides' look from ``spec``: ``slides`` and the terminal's size and colours."""
    css = spec.slides.css or ""
    if css.startswith("data:"):
        header, _, payload = css.partition(",")
        css = base64.b64decode(payload).decode("utf-8") if header.endswith(";base64") else unquote(payload)
    palette = spec.terminal.palette()
    return Look(
        theme=spec.slides.theme,
        width=spec.terminal.width,
        height=spec.terminal.height,
        css=css,
        classes=spec.slides.classes or "",
        band=frame_px(spec),
        band_color=palette["background"] if palette else None,
        background=palette["background"] if palette else None,
    )


def page(slide: Slide, look: Look | SlideTheme, workspace: Path) -> str:
    """The HTML page of a slide: ``<section class="slide KIND">`` with an ``h1`` and its content.

    ``look`` is the spec's (a theme name stands for the defaults); a slide's own ``theme`` wins.
    """
    look = look if isinstance(look, Look) else Look(theme=look)
    theme = slide.theme or look.theme
    footer = script = ""
    if slide.table is not None:
        kind = "table"
        body, footer = _table(slide.table, slide)
        script = _FOLLOW_MARK
    elif slide.mermaid is not None:
        kind, body = "mermaid", f'<pre class="mermaid">{html.escape(slide.mermaid)}</pre>'
    elif slide.code is not None:
        kind, body = "code", _code(slide.code, slide.lang, theme, look, titled=bool(slide.title))
    elif slide.points is not None:
        kind, body = "points", _points(slide.points, slide.current)
    else:
        assert slide.image is not None
        kind = "image"
        body = f'<img alt="{html.escape(slide.title or "")}" src="{_image_src(slide.image, workspace)}">'
    height = look.design_height
    band = look.design_px(look.band)
    sizes = {
        "zoom": f"{look.width / DESIGN_WIDTH:.6f}",
        "height": height,
        "section_height": height - band,
        "band": band,
        "diagram_height": round((height - band) * (0.78 if slide.title else 0.92)),
        "title_pad": round(height * 0.03),
        "code_pad": round(height * 0.025),
        "points_top": round(height * 0.04),
        "gap": round(height * 0.026),
        "item_pad": round(height * 0.012),
    }
    colors = COLORS[theme]
    if theme == "dark" and look.background:
        colors = colors | {"bg": look.background}
    band_color = look.band_color or colors["bg"]
    style = (
        _LAYOUT.format(**colors, **sizes, band_color=band_color)
        + _LOOK.format(**colors, **sizes)
        + _STATES
        + look.css
    )
    title = f"<h1>{html.escape(slide.title)}</h1>" if slide.title else ""
    footer = f"<footer>{footer}</footer>" if footer else ""
    focus = f' data-mermaid-focus="{html.escape(slide.focus, quote=True)}"' if slide.focus else ""
    classes = " ".join(["slide", kind, *look.classes.split()])
    return (
        f'<!doctype html><html><head><meta charset="utf-8"><style>{style}</style></head>'
        f'<body data-mermaid-theme="{MERMAID_THEMES[theme]}"{focus}>'
        f'<section class="{html.escape(classes, quote=True)}">'
        f'{title}<div class="content">{body}</div>{footer}'
        "</section>" + (f"<script>{script}</script>" if script else "") + "</body></html>"
    )


def _table(table: SlideTable, slide: Slide) -> tuple[str, str]:
    """The table of the slide's page, and the page counter when it has several."""
    rows = list(enumerate(table.rows, 1))
    footer = ""
    if slide.rows:
        pages = -(-len(rows) // slide.rows)
        shown = slide.shown_page
        rows = rows[(shown - 1) * slide.rows : shown * slide.rows]
        footer = f"{shown}/{pages}" if pages > 1 else ""
    head = "".join(f"<th>{_INLINE.renderInline(cell)}</th>" for cell in table.header)
    body = "".join(
        ('<tr class="mark">' if number == slide.highlight else "<tr>")
        + "".join(f"<td>{_INLINE.renderInline(cell)}</td>" for cell in row)
        + "</tr>"
        for number, row in rows
    )
    thead = f"<thead><tr>{head}</tr></thead>" if head else ""
    return f"<table>{thead}<tbody>{body}</tbody></table>", footer


def _points(points: list[str], current: int | None) -> str:
    """The points as a list; ``current`` (from 1) marked, the ones before and after it dimmed."""
    items = []
    for number, point in enumerate(points, 1):
        state = (
            ""
            if current is None
            else "current"
            if number == current
            else "done"
            if number < current
            else "next"
        )
        items.append(
            f'<li class="{state}">{_INLINE.renderInline(point)}</li>'
            if state
            else f"<li>{_INLINE.renderInline(point)}</li>"
        )
    return f'<ul class="points">{"".join(items)}</ul>'


def _code(code: str, lang: str | None, theme: SlideTheme, look: Look, *, titled: bool) -> str:
    """The code, highlighted by Pygments, as large as fits the slide."""
    from pygments import highlight
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import TextLexer, get_lexer_by_name
    from pygments.util import ClassNotFound

    try:
        lexer = get_lexer_by_name(lang) if lang else TextLexer()
    except ClassNotFound:
        lexer = TextLexer()
    formatter = HtmlFormatter(nowrap=True, noclasses=True, style=CODE_STYLES[theme])
    lines = code.expandtabs(4).split("\n")
    columns = max((len(line) for line in lines), default=1) or 1
    # Monospace glyphs are about 0.6em wide; lines are 1.35em high.
    room = (look.design_height - look.design_px(look.band)) * (0.70 if titled else 0.80)
    size = min(30.72, 0.85 * DESIGN_WIDTH / (columns * 0.6), room / (len(lines) * 1.35))
    return (
        f'<pre class="code" style="font-size:{size:.2f}px"><code>'
        f"{highlight(code.expandtabs(4), lexer, formatter).rstrip()}</code></pre>"
    )


def _image_src(image: str, workspace: Path) -> str:
    if image.startswith("data:"):
        return html.escape(image)
    path = (workspace / image).resolve()
    if not path.is_relative_to(workspace.resolve()):
        raise RenderError(f"slide: {image} is outside the workspace")
    if not path.is_file():
        raise RenderError(f"slide: {image} is not a file in the workspace")
    return path.as_uri()
