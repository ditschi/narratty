"""Slides: a table, Mermaid diagram or image on a full-screen page.

Each slide becomes an HTML file that :mod:`.browser` captures like a browser view, but
without the address bar. Loaded from a file, the page can show workspace images and
embedded ones of any size. Mermaid diagrams are drawn during the capture.
"""

from __future__ import annotations

import html
from pathlib import Path

from markdown_it import MarkdownIt

from narratty.errors import RenderError
from narratty.spec.model import Slide, SlideTable, SlideTheme

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

_STYLE = """
html,body{{margin:0;height:100%}}
body{{display:flex;flex-direction:column;background:{bg};color:{fg};font-family:
'DejaVu Sans','Noto Color Emoji',sans-serif}}
header{{padding:3vh 4vw 0;font-size:3.2vw;font-weight:bold;color:{accent}}}
main{{flex:1;min-height:0;display:flex;overflow:hidden}}
main>*{{margin:auto}}
footer{{position:fixed;right:2vw;bottom:1.5vh;font-size:1.6vw;opacity:.7}}
table{{border-collapse:collapse;max-width:94vw;font-size:2.2vw}}
th,td{{padding:.45em .8em;border-bottom:1px solid {line};text-align:left}}
th{{color:{accent}}}
tr.mark{{background:{mark};outline:3px solid {accent}}}
code{{font-family:'JetBrains Mono',monospace;color:{code}}}
a{{color:{link}}}
img{{max-width:94vw;max-height:100%;object-fit:contain}}
pre.mermaid{{width:94vw;text-align:center;font:1.6vw 'JetBrains Mono',monospace;white-space:pre-wrap}}
pre.mermaid svg{{max-width:100%!important;max-height:{diagram_height};height:auto}}
.narratty-focus>:is(rect,polygon,circle,path),.narratty-focus :is(.label-container,.label-container *){{
stroke:{accent}!important;stroke-width:4px!important;filter:drop-shadow(0 0 5px {accent})}}
"""
# A table taller than the slide moves up until the highlighted row is in the middle.
_FOLLOW_MARK = (
    "const m=document.querySelector('main'),t=m.querySelector('table'),r=t.querySelector('tr.mark'),"
    "h=m.clientHeight;if(r&&t.offsetHeight>h){const y=Math.min(Math.max(r.offsetTop+r.offsetHeight/2-h/2,0),"
    "t.offsetHeight-h);t.style.transform='translateY('+(-y)+'px)'}"
)
_INLINE = MarkdownIt("commonmark", {"html": False}).disable("image")


def page(slide: Slide, theme: SlideTheme, workspace: Path) -> str:
    """The HTML page of a table, Mermaid or image slide; ``theme`` unless the slide sets one."""
    theme = slide.theme or theme
    footer = script = ""
    if slide.table is not None:
        body, footer = _table(slide.table, slide)
        script = _FOLLOW_MARK
    elif slide.mermaid is not None:
        body = f'<pre class="mermaid">{html.escape(slide.mermaid)}</pre>'
    else:
        assert slide.image is not None
        body = f'<img alt="{html.escape(slide.title or "")}" src="{_image_src(slide.image, workspace)}">'
    style = _STYLE.format(**COLORS[theme], diagram_height="78vh" if slide.title else "92vh")
    header = f"<header>{html.escape(slide.title)}</header>" if slide.title else ""
    focus = f' data-mermaid-focus="{html.escape(slide.focus, quote=True)}"' if slide.focus else ""
    return (
        f'<!doctype html><html><head><meta charset="utf-8"><style>{style}</style></head>'
        f'<body data-mermaid-theme="{MERMAID_THEMES[theme]}"{focus}>{header}<main>{body}</main>{footer}'
        + (f"<script>{script}</script>" if script else "")
        + "</body></html>"
    )


def _table(table: SlideTable, slide: Slide) -> tuple[str, str]:
    """The table of the slide's page, and the page counter when it has several."""
    rows = list(enumerate(table.rows, 1))
    footer = ""
    if slide.rows:
        pages = -(-len(rows) // slide.rows)
        shown = slide.shown_page
        rows = rows[(shown - 1) * slide.rows : shown * slide.rows]
        footer = f"<footer>{shown}/{pages}</footer>" if pages > 1 else ""
    head = "".join(f"<th>{_INLINE.renderInline(cell)}</th>" for cell in table.header)
    body = "".join(
        ('<tr class="mark">' if number == slide.highlight else "<tr>")
        + "".join(f"<td>{_INLINE.renderInline(cell)}</td>" for cell in row)
        + "</tr>"
        for number, row in rows
    )
    thead = f"<thead><tr>{head}</tr></thead>" if head else ""
    return f"<table>{thead}<tbody>{body}</tbody></table>", footer


def _image_src(image: str, workspace: Path) -> str:
    if image.startswith("data:"):
        return html.escape(image)
    path = (workspace / image).resolve()
    if not path.is_relative_to(workspace.resolve()):
        raise RenderError(f"slide: {image} is outside the workspace")
    if not path.is_file():
        raise RenderError(f"slide: {image} is not a file in the workspace")
    return path.as_uri()
