"""Markdown text to a flat list of headings, spoken text, code blocks and comments.

markdown-it-py with the ``admon`` plugin reads the text the way mkdocs does for what
matters here. What is left out of the video (collapsed blocks, raw HTML) is dropped in
this pass; what to do with the rest is decided in :mod:`.scenes`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode
from mdit_py_plugins.admon import admon_plugin
from mdit_py_plugins.footnote import footnote_plugin

from narratty.spec.markdown.source import Line


@dataclass(frozen=True)
class Block:
    """Where a block starts (1-based)."""

    file: Path
    line: int


@dataclass(frozen=True)
class Heading(Block):
    level: int
    title: str
    slug: str
    """The id mkdocs gives the heading (attr_list id, else the TOC slug)."""


@dataclass(frozen=True)
class Text(Block):
    """A paragraph, list item or quote, as plain text."""

    text: str
    links: tuple[tuple[str, str], ...] = ()
    """``(text, href)`` of each link, in order."""
    callout: tuple[str, str | None] | None = None
    """``(type, title)`` of the admonition or alert this paragraph opens; title None: none given."""
    footnotes: tuple[tuple[int, str], ...] = ()
    """``(position, text)`` of each footnote referred to: where its sentence ends in ``text``."""


@dataclass(frozen=True)
class Code(Block):
    lang: str
    content: str
    id: str | None = None
    title: str | None = None
    options: tuple[str, ...] = ()
    """Space-separated words of the ``narratty="…"`` attribute."""


@dataclass(frozen=True)
class Comment(Block):
    """The inside of an HTML comment (``<!-- … -->``)."""

    text: str


@dataclass(frozen=True)
class Image(Block):
    """An image that stands alone in its paragraph."""

    src: str
    alt: str


@dataclass(frozen=True)
class Table(Block):
    """A table: its cells as plain text (spoken) and as inline Markdown (shown)."""

    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    row_lines: tuple[int, ...]
    header_source: tuple[str, ...]
    rows_source: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class Dropped(Block):
    """Something left out of the video, kept so ``plan --sources`` can say why."""

    what: str
    why: str = "not part of the video"


_HEADING_ATTRS = re.compile(r"\s*\{:?\s*(?P<attrs>[^}]*)\}\s*$")
_ATTR = re.compile(r"#(?P<id>[\w-]+)|\.[\w-]+|(?P<key>[\w-]+)=(?P<value>\"[^\"]*\"|'[^']*'|[^\s}]+)")
_ALERT = re.compile(r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*", re.IGNORECASE)
_TASK = re.compile(r"^\[[ xX]\]\s+")
_FOOTNOTE_REF = re.compile(r"\s*\ue000([^\ue001]*)\ue001")
_SENTENCE_END = re.compile(r"[.!?…:;](?=\s|$)")
_TITLE = re.compile(r'"(?P<title>[^"]*)"')
FOOTNOTE = "footnote definition"
_INLINE_HILITE = re.compile(r"^#!\w+\s+")
SENTENCE_END = (".", "!", "?", ":", ";", "…")
_COMMENT = re.compile(r"^\s*<!--(?P<text>.*?)-->\s*$", re.DOTALL)
_DETAILS_OPEN = re.compile(r"<details\b", re.IGNORECASE)
_DETAILS_CLOSE = re.compile(r"</details\s*>", re.IGNORECASE)
_DROPPED = {"code_block": "indented code block"}


def parse_blocks(lines: list[Line]) -> list[Block]:
    """The blocks of ``lines`` in reading order."""
    parser = MarkdownIt("commonmark").enable("table").use(admon_plugin).use(footnote_plugin)
    tree = SyntaxTreeNode(parser.parse("\n".join(line.text for line in lines) + "\n"))
    walker = _Walker(lines)
    walker.footnotes = _footnotes(tree)
    walker.walk(tree.children)
    return walker.blocks


def _footnotes(tree: SyntaxTreeNode) -> dict[str, str]:
    """Each footnote's text by label (the plugin moves the definitions to the end)."""
    found = {}
    for block in (node for node in tree.children if node.type == "footnote_block"):
        for note in block.children:
            parts = [_plain(child.children[0]) for child in note.children if child.type == "paragraph"]
            found[str(note.meta.get("label", ""))] = " ".join(part for part in parts if part)
    return found


class _Walker:
    def __init__(self, lines: list[Line]) -> None:
        self.lines = lines
        self.blocks: list[Block] = []
        self.slugs: set[str] = set()
        self.footnotes: dict[str, str] = {}

    def at(self, node: SyntaxTreeNode) -> tuple[Path, int]:
        line = self.lines[min(node.map[0], len(self.lines) - 1)] if node.map else self.lines[-1]
        return line.file, line.number

    def walk(
        self,
        nodes: list[SyntaxTreeNode],
        *,
        item: bool = False,
        quote: bool = False,
        callout: tuple[str, str | None] | None = None,
    ) -> None:
        details = 0  # open <details> blocks: left out with everything inside
        for node in nodes:
            if callout is not None and node.type != "paragraph":
                # The admonition starts with a block: its type is said on its own.
                self.blocks.append(Text(*self.at(node), "", callout=callout))
            if node.type == "html_block":
                details = self.html(node, details)
            elif details:
                continue
            elif node.type == "paragraph":
                self.text(node, item=item, quote=quote, callout=callout)
                quote = False  # only a quote's first paragraph carries an alert marker
            else:
                self.block(node)
            callout = None

    def block(self, node: SyntaxTreeNode) -> None:
        if node.type == "heading":
            self.heading(node)
        elif node.type in ("bullet_list", "ordered_list"):
            for list_item in node.children:
                self.walk(list_item.children, item=True)
        elif node.type == "blockquote":
            self.walk(node.children, quote=True)
        elif node.type == "admonition":
            self.admonition(node)
        elif node.type == "fence":
            self.blocks.append(self.code(node))
        elif node.type == "table":
            self.blocks.append(self.table(node))
        elif node.type == "footnote_block":
            self.footnote_definitions(node)
        elif node.type in _DROPPED:
            self.blocks.append(Dropped(*self.at(node), _DROPPED[node.type]))

    def admonition(self, node: SyntaxTreeNode) -> None:
        if node.markup == "???":  # collapsed: left out with everything inside
            self.blocks.append(Dropped(*self.at(node), "collapsed admonition"))
            return
        title = _TITLE.search(node.info)
        kind = str(node.meta.get("tag", "")).lower()
        self.walk(
            [child for child in node.children if child.type != "admonition_title"],
            callout=(kind, title["title"] or None if title else None),
        )

    def footnote_definitions(self, node: SyntaxTreeNode) -> None:
        for note in node.children:
            where = next((self.at(child) for child in note.children if child.map), self.at(note))
            self.blocks.append(Dropped(*where, FOOTNOTE))

    def html(self, node: SyntaxTreeNode, details: int) -> int:
        """Record a comment; return the number of ``<details>`` open after ``node``."""
        opened = len(_DETAILS_OPEN.findall(node.content)) - len(_DETAILS_CLOSE.findall(node.content))
        if details == 0 and (comment := _COMMENT.match(node.content)):
            self.blocks.append(Comment(*self.at(node), comment["text"]))
        elif details == 0:
            self.blocks.append(Dropped(*self.at(node), "<details> block" if opened > 0 else "raw HTML"))
        return max(0, details + opened)

    def heading(self, node: SyntaxTreeNode) -> None:
        title = _plain(node.children[0]) if node.children else ""
        anchor = None
        if match := _HEADING_ATTRS.search(title):
            anchor = next((m["id"] for m in _ATTR.finditer(match["attrs"]) if m["id"]), None)
            title = title[: match.start()].strip()
        slug = _unique(anchor or slugify(title), self.slugs)
        self.blocks.append(Heading(*self.at(node), int(node.tag[1]), title, slug))

    def text(
        self, node: SyntaxTreeNode, *, item: bool, quote: bool, callout: tuple[str, str | None] | None
    ) -> None:
        if node.children and (image := _only_image(node.children[0])) is not None:
            self.blocks.append(Image(*self.at(node), str(image.attrs.get("src", "")), _plain(image)))
            return
        for _ in _images(node.children[0]) if node.children else []:
            self.blocks.append(Dropped(*self.at(node), "image", "left out (inline image)"))
        text = _plain(node.children[0], refs=True) if node.children else ""
        if item:
            text = _TASK.sub("", text)  # a task list item: "[ ] " or "[x] "
        if quote and (alert := _ALERT.match(text)):
            text = text[alert.end() :]
            callout = (alert[1].lower(), None)
        text, refs = _footnote_refs(text)
        if callout is None and (
            not text or _HEADING_ATTRS.fullmatch(text)
        ):  # empty, an image, `{ .annotate }`
            return
        if item and text and not text.endswith(SENTENCE_END):
            text += "."
        links = tuple(_links(node.children[0])) if node.children else ()
        notes = tuple((_sentence_end(text, at), self.footnotes.get(label, "")) for at, label in refs)
        self.blocks.append(Text(*self.at(node), text, links, callout, notes))

    def code(self, node: SyntaxTreeNode) -> Code:
        lang, attrs = parse_info(node.info)
        return Code(
            *self.at(node),
            lang=lang,
            content=node.content,
            id=attrs.get("#"),
            title=attrs.get("title"),
            options=tuple(attrs.get("narratty", "").split()),
        )

    def table(self, node: SyntaxTreeNode) -> Table:
        def cells(row: SyntaxTreeNode) -> tuple[str, ...]:
            return tuple(_plain(cell.children[0]) if cell.children else "" for cell in row.children)

        def sources(row: SyntaxTreeNode) -> tuple[str, ...]:
            return tuple(cell.children[0].content if cell.children else "" for cell in row.children)

        parts = {part.type: part for part in node.children}
        head = parts["thead"].children if "thead" in parts else []
        body = parts["tbody"].children if "tbody" in parts else []
        return Table(
            *self.at(node),
            header=cells(head[0]) if head else (),
            rows=tuple(cells(row) for row in body),
            row_lines=tuple(self.at(row)[1] for row in body),
            header_source=sources(head[0]) if head else (),
            rows_source=tuple(sources(row) for row in body),
        )


def parse_info(info: str) -> tuple[str, dict[str, str]]:
    """Language and attributes of a fence line; ``#`` holds the id.

    Takes ``lang {#id key="value"}`` and the brace-less ``lang key="value"``.
    """
    lang, _, rest = info.strip().partition(" ")
    if lang.startswith("{"):
        lang, rest = "", info.strip()
    attrs: dict[str, str] = {}
    for match in _ATTR.finditer(rest):
        if match["id"]:
            attrs["#"] = match["id"]
        elif match["key"]:
            value = match["value"]
            attrs[match["key"]] = value[1:-1] if value[:1] in "\"'" else value
    return lang.lower(), attrs


def _only_image(inline: SyntaxTreeNode) -> SyntaxTreeNode | None:
    """The image when it is all there is in the paragraph (an attr_list may follow)."""
    images = [child for child in inline.children if child.type == "image"]
    rest = "".join(child.content for child in inline.children if child.type == "text").strip()
    others = [child for child in inline.children if child.type not in ("image", "text", "softbreak")]
    if len(images) == 1 and not others and (not rest or _HEADING_ATTRS.fullmatch(rest)):
        return images[0]
    return None


def _images(node: SyntaxTreeNode) -> list[SyntaxTreeNode]:
    """Images anywhere in inline Markdown, also inside links (badges)."""
    found: list[SyntaxTreeNode] = []
    for child in node.children:
        if child.type == "image":
            found.append(child)
        elif child.children:
            found += _images(child)
    return found


def _footnote_refs(text: str) -> tuple[str, list[tuple[int, str]]]:
    """``text`` without its footnote markers, and where each was, with its label."""
    refs: list[tuple[int, str]] = []
    parts: list[str] = []
    length = 0
    last = 0
    for match in _FOOTNOTE_REF.finditer(text):
        parts.append(text[last : match.start()])
        length += match.start() - last
        refs.append((length, match[1]))
        last = match.end()
    parts.append(text[last:])
    clean = "".join(parts)
    lead = len(clean) - len(clean.lstrip())
    return clean.strip(), [(max(at - lead, 0), label) for at, label in refs]


def _sentence_end(text: str, at: int) -> int:
    """Where the sentence that goes on at ``at`` ends in ``text``."""
    match = _SENTENCE_END.search(text, at)
    return match.end() if match else len(text)


def _links(node: SyntaxTreeNode) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for child in node.children:
        if child.type == "link":
            found.append((_plain(child), str(child.attrs.get("href", ""))))
        elif child.children:
            found += _links(child)
    return found


def _plain(node: SyntaxTreeNode, *, refs: bool = False) -> str:
    """Inline Markdown as the words a reader sees; images and raw HTML are dropped.

    Footnote references are dropped too, or with ``refs`` marked for :func:`_footnote_refs`.
    """
    parts: list[str] = []
    for child in node.children:
        if child.type == "text":
            parts.append(child.content)
        elif child.type == "code_inline":
            parts.append(_INLINE_HILITE.sub("", child.content))
        elif child.type in ("softbreak", "hardbreak"):
            parts.append(" ")
        elif child.type == "footnote_ref":
            parts.append(f"\ue000{child.meta.get('label', '')}\ue001" if refs else "")
        elif child.type not in ("image", "html_inline", "footnote_anchor"):
            parts.append(_plain(child, refs=refs))
    return " ".join("".join(parts).split())


def slugify(title: str) -> str:
    """The TOC slug of ``title``: ``pymdownx.slugs.slugify(case="lower")``."""
    slug = re.sub(r"</?[^>]*>", "", unicodedata.normalize("NFC", title)).strip().lower()
    return re.sub(r"[^\w\- ]", "", slug).replace(" ", "-")


def _unique(slug: str, seen: set[str]) -> str:
    """Python-Markdown's TOC: a repeated id gets ``_1``, ``_2``, …"""
    while slug in seen or not slug:
        match = re.match(r"^(.*)_([0-9]+)$", slug)
        slug = f"{match[1]}_{int(match[2]) + 1}" if match else f"{slug}_1"
    seen.add(slug)
    return slug
