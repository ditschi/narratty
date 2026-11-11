"""Markdown text to a flat list of headings, spoken text, code blocks and comments.

markdown-it-py with the ``admon`` plugin reads the text the way mkdocs does for what
matters here. What is left out of the video (tables, collapsed blocks, raw HTML) is
dropped in this pass; what to do with the rest is decided in :mod:`.scenes`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode
from mdit_py_plugins.admon import admon_plugin

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
class Dropped(Block):
    """Something left out of the video, kept so ``plan --sources`` can say why."""

    what: str


_HEADING_ATTRS = re.compile(r"\s*\{:?\s*(?P<attrs>[^}]*)\}\s*$")
_ATTR = re.compile(r"#(?P<id>[\w-]+)|\.[\w-]+|(?P<key>[\w-]+)=(?P<value>\"[^\"]*\"|'[^']*'|[^\s}]+)")
_ALERT = re.compile(r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*", re.IGNORECASE)
_INLINE_HILITE = re.compile(r"^#!\w+\s+")
_SENTENCE_END = (".", "!", "?", ":", ";", "…")
_COMMENT = re.compile(r"^\s*<!--(?P<text>.*?)-->\s*$", re.DOTALL)
_DETAILS_OPEN = re.compile(r"<details\b", re.IGNORECASE)
_DETAILS_CLOSE = re.compile(r"</details\s*>", re.IGNORECASE)
_DROPPED = {"table": "table", "code_block": "indented code block"}


def parse_blocks(lines: list[Line]) -> list[Block]:
    """The blocks of ``lines`` in reading order."""
    parser = MarkdownIt("commonmark").enable("table").use(admon_plugin)
    tree = SyntaxTreeNode(parser.parse("\n".join(line.text for line in lines) + "\n"))
    walker = _Walker(lines)
    walker.walk(tree.children)
    return walker.blocks


class _Walker:
    def __init__(self, lines: list[Line]) -> None:
        self.lines = lines
        self.blocks: list[Block] = []
        self.slugs: set[str] = set()

    def at(self, node: SyntaxTreeNode) -> tuple[Path, int]:
        line = self.lines[min(node.map[0], len(self.lines) - 1)] if node.map else self.lines[-1]
        return line.file, line.number

    def walk(self, nodes: list[SyntaxTreeNode], *, item: bool = False, quote: bool = False) -> None:
        details = 0  # open <details> blocks: left out with everything inside
        for node in nodes:
            if node.type == "html_block":
                details = self.html(node, details)
            elif details:
                continue
            elif node.type == "paragraph":
                self.text(node, item=item, quote=quote)
                quote = False  # only a quote's first paragraph carries an alert marker
            else:
                self.block(node)

    def block(self, node: SyntaxTreeNode) -> None:
        if node.type == "heading":
            self.heading(node)
        elif node.type in ("bullet_list", "ordered_list"):
            for list_item in node.children:
                self.walk(list_item.children, item=True)
        elif node.type == "blockquote":
            self.walk(node.children, quote=True)
        elif node.type == "admonition":
            if node.markup == "???":  # collapsed: left out with everything inside
                self.blocks.append(Dropped(*self.at(node), "collapsed admonition"))
            else:
                self.walk([child for child in node.children if child.type != "admonition_title"])
        elif node.type == "fence":
            self.blocks.append(self.code(node))
        elif node.type in _DROPPED:
            self.blocks.append(Dropped(*self.at(node), _DROPPED[node.type]))

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

    def text(self, node: SyntaxTreeNode, *, item: bool, quote: bool) -> None:
        text = _plain(node.children[0]) if node.children else ""
        if quote:
            text = _ALERT.sub("", text)
        if not text or _HEADING_ATTRS.fullmatch(text):  # empty, an image, or `{ .annotate }`
            return
        if item and not text.endswith(_SENTENCE_END):
            text += "."
        self.blocks.append(Text(*self.at(node), text))

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


def _plain(node: SyntaxTreeNode) -> str:
    """Inline Markdown as the words a reader sees; images and raw HTML are dropped."""
    parts: list[str] = []
    for child in node.children:
        if child.type == "text":
            parts.append(child.content)
        elif child.type == "code_inline":
            parts.append(_INLINE_HILITE.sub("", child.content))
        elif child.type in ("softbreak", "hardbreak"):
            parts.append(" ")
        elif child.type not in ("image", "html_inline"):
            parts.append(_plain(child))
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
