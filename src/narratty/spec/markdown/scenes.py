"""Blocks of a Markdown doc to scenes: section selection, narration and actions."""

from __future__ import annotations

import base64
import difflib
import posixpath
import re
import shlex
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from narratty.spec.markdown import EntryError, ExpandedScene
from narratty.spec.markdown.links import LinkError, resolve_link
from narratty.spec.markdown.parse import (
    SENTENCE_END,
    Block,
    Code,
    Comment,
    Dropped,
    Heading,
    Image,
    Table,
    Text,
)
from narratty.spec.markdown.shell import Command, clean_command, split_commands
from narratty.spec.markdown.source import fail
from narratty.spec.model import (
    SLIDE_IMAGE_TYPES,
    HeadingOverlays,
    MarkdownEntry,
    MarkdownNarration,
    to_ms,
)

SHELL_LANGS = ("bash", "sh", "shell")
BLOCK_OPTIONS = ("no-run", "hidden", "expect-failure")
COMMENT_KINDS = ("skip", "say", "overlay", "hidden", "browser", "pause", "table", "slide")
SLIDE_KEYS = ("title", "theme", "rows", "html")
TABLE_KEYS = ("say", "pause", "title", "theme", "rows")
VISUALS = "a table, image or mermaid block"
NO_RUN_HOLD_MS = 1000
IMAGE_HOLD_MS = 3000  # an image scene without narration
MAX_URL_CHARS = 2 * 1024 * 1024  # Chromium does not load longer URLs
_COMMENT = re.compile(r"^\s*narratty:\s*(?P<kind>[\w-]*)(?P<body>.*)$", re.DOTALL)
_FIELD = re.compile(r"\{([^{}]+)\}")


@dataclass(frozen=True)
class Note:
    """What became of one part of the doc (for ``narratty plan --sources``)."""

    file: Path
    line: int
    scene: str | None
    what: str


@dataclass(frozen=True)
class Expansion:
    scenes: list[ExpandedScene]
    notes: list[Note]


def build_scenes(
    blocks: list[Block], entry: MarkdownEntry, path: Path, narration: MarkdownNarration
) -> Expansion:
    """The scenes of ``blocks`` for ``entry``, in the order of ``entry.sections``."""
    builder = _Builder(entry.id_prefix or id_part(path.stem) or "doc", narration, entry)
    for start, end in select_sections(blocks, entry.sections):
        builder.add(blocks[start:end])
    builder.check_overrides(blocks)
    return Expansion(builder.scenes, sorted(builder.notes, key=lambda note: (str(note.file), note.line)))


# ── sections ──────────────────────────────────────────────────────────────────


def select_sections(blocks: list[Block], sections: Sequence[str | list[str]] | None) -> list[tuple[int, int]]:
    """``(start, end)`` ranges of ``blocks`` for the selected sections, in their order."""
    if sections is None:
        return [(0, len(blocks))]
    headings = [index for index, block in enumerate(blocks) if isinstance(block, Heading)]
    ranges = []
    for number, selection in enumerate(sections):
        path = [selection] if isinstance(selection, str) else selection
        start = _find(blocks, headings, path, (number,))
        ranges.append((start, _section_end(blocks, start)))
    return ranges


def _section_end(blocks: list[Block], start: int) -> int:
    level = _heading(blocks[start]).level
    for index in range(start + 1, len(blocks)):
        block = blocks[index]
        if isinstance(block, Heading) and block.level <= level:
            return index
    return len(blocks)


def _find(blocks: list[Block], headings: list[int], path: list[str], loc: tuple[int | str, ...]) -> int:
    """The heading that ``path`` names, each part inside the previous one's section."""
    within = (0, len(blocks))
    found = -1
    for part in path:
        candidates = [index for index in headings if within[0] <= index < within[1] and index != found]
        matches = [i for i in candidates if _heading(blocks[i]).slug == part] or [
            i for i in candidates if _heading(blocks[i]).title.casefold() == part.casefold()
        ]
        if not matches:
            names = [_heading(blocks[i]).slug for i in candidates]
            raise EntryError(
                ("sections", *loc), f"no section {part!r} in the doc{_did_you_mean(part, names)}"
            )
        if len(matches) > 1 and part == path[-1]:
            lines = ", ".join(str(blocks[i].line) for i in matches)
            raise EntryError(
                ("sections", *loc),
                f"{part!r} names {len(matches)} headings (lines {lines}); "
                "pick one with a list path such as [parent, heading]",
            )
        found = matches[0]
        within = (found, _section_end(blocks, found))
    return found


def _heading(block: Block) -> Heading:
    assert isinstance(block, Heading)
    return block


def _did_you_mean(name: str, names: Sequence[str]) -> str:
    match = difflib.get_close_matches(name, names, n=1)
    return f" (did you mean {match[0]!r}?)" if match else ""


# ── scenes ────────────────────────────────────────────────────────────────────


class _Builder:
    def __init__(self, prefix: str, narration: MarkdownNarration, entry: MarkdownEntry) -> None:
        self.prefix = prefix
        self.narration = narration
        self.entry = entry
        self.defaults = entry.defaults.model_dump(exclude_none=True)
        self.scenes: list[ExpandedScene] = []
        self.notes: list[Note] = []
        self.section = ""
        self.count = 0
        self.spoken: list[str] = []
        self.unassigned: list[tuple[Block, str]] = []  # notes waiting for their scene's id
        self.overlays: list[tuple[int | None, dict[str, Any]]] = []  # (heading level, action)
        self.trail: dict[int, str] = {}  # breadcrumb: level → heading
        self.skip = False
        self.image = False  # an image or web page waits for its scene
        self.link: tuple[Comment, dict[str, Any]] | None = None  # a browser comment's options
        self.table: tuple[Comment, dict[str, Any]] | None = None  # a table comment's options
        self.slide: tuple[Comment, dict[str, Any]] | None = None  # a slide comment's options
        self.pages: list[dict[str, Any]] = []  # later pages of the table on screen
        self.pages_block: Block | None = None
        self.used: set[str] = set()

    def add(self, blocks: list[Block]) -> None:
        for block in blocks:
            self.check_pending(block)
            if isinstance(block, Heading):
                self.heading(block)
            elif isinstance(block, Comment):
                self.comment(block)
            elif isinstance(block, Dropped):
                self.note(block, None, f"{block.what}: not part of the video")
            elif self.skip:
                self.skip = False
                if isinstance(block, Table):
                    self.table = None
                self.slide = None
                self.note(block, None, f"{_kind(block)}: left out by a skip comment")
            else:
                self.content(block)
        self.check_pending(None)
        self.flush()

    def check_pending(self, block: Block | None) -> None:
        """Comments waiting for the next block must get one they apply to (None: section end)."""
        if isinstance(block, (Comment, Dropped)):
            return
        if self.link is not None and block is not None:
            self.open_link(block)
        if self.table is not None and not isinstance(block, Table):
            self.no_block(self.table, "table", "a table")
        if self.slide is not None and (block is None or not _visual(block)):
            self.no_block(self.slide, "slide", VISUALS)

    def content(self, block: Block) -> None:
        if isinstance(block, Text):
            self.text(block)
        elif isinstance(block, Code):
            self.code(block)
        elif isinstance(block, Image):
            self.show_image(block)
        elif isinstance(block, Table):
            self.show_table(block)

    # ── blocks ──

    def heading(self, block: Heading) -> None:
        self.flush()
        self.section, self.count = id_part(block.slug), 0
        # Overlays of headings that got no scene give way to this one.
        self.overlays = [
            (level, action) for level, action in self.overlays if level is None or level < block.level
        ]
        settings = self.entry.heading_overlays
        if settings is None or block.level > settings.levels:
            return
        self.trail = {level: title for level, title in self.trail.items() if level < block.level}
        if settings.breadcrumb and block.level >= 2:
            self.trail[block.level] = block.title
        else:
            style = f"heading-{min(block.level, 4)}"
            self.overlays.append((block.level, {"overlay": {"text": block.title, "style": style}}))

    def text(self, block: Text) -> None:
        if self.narration == "all":
            self.spoken.append(block.text)
            self.unassigned.append((block, "paragraph: spoken"))
        else:
            self.note(block, None, "paragraph: not spoken (narration: none)")

    def comment(self, block: Comment) -> None:
        match = _COMMENT.match(block.text)
        if match is None:
            return  # an ordinary comment
        kind, body = match["kind"], match["body"].strip()
        if kind == "skip":
            self.skip = True
        elif kind == "say":
            self.spoken.append(" ".join(body.split()))
            self.unassigned.append((block, "say comment: spoken"))
        elif kind == "overlay":
            self.overlays.append((None, {"overlay": _yaml_value(body, block, kind)}))
            self.unassigned.append((block, "overlay comment"))
        elif kind == "browser":
            self.browser_comment(block, body)
        elif kind == "pause":
            self.pause(block, body)
        elif kind == "table":
            self.table_comment(block, body)
        elif kind == "slide":
            self.slide_comment(block, body)
        elif kind == "hidden":
            commands = split_commands(body)
            _check_placeholders(commands, block, 0)
            scene_id = self.next_id(None)
            self.emit(block, {"id": scene_id, "hidden": True, "actions": _runs(commands)})
            self.note(block, scene_id, f"hidden comment: {len(commands)} command(s), not shown")
        else:
            raise fail(
                block.file,
                block.line,
                f"unknown narratty comment {kind!r}; expected one of {', '.join(COMMENT_KINDS)}",
            )

    def browser_comment(self, block: Comment, body: str) -> None:
        """Open a page from where the next paragraph starts: a URL, or one of its links."""
        value = _yaml_value(body, block, "browser") if body else {}
        options = {"url": value} if isinstance(value, str) else value
        if not isinstance(options, dict):
            raise fail(block.file, block.line, "browser comment: expected a URL or a mapping")
        if "url" in options:
            self.show_view(block, {"browser": options}, f"browser comment: opens {options['url']}")
        else:
            self.link = (block, options)

    def open_link(self, block: Block) -> None:
        """Apply the pending browser comment to ``block``, which must be a paragraph with a link."""
        assert self.link is not None
        comment, options = self.link
        self.link = None
        links = block.links if isinstance(block, Text) else ()
        choice = options.pop("link", None)
        if not links:
            raise fail(comment.file, comment.line, "browser comment: the next paragraph has no link")
        if choice is None:
            text, href = links[0]
        elif isinstance(choice, int) and not isinstance(choice, bool):
            if not 1 <= choice <= len(links):
                raise fail(
                    comment.file, comment.line, f"browser comment: the paragraph has {len(links)} link(s)"
                )
            text, href = links[choice - 1]
        else:
            named = [link for link in links if link[0].casefold() == str(choice).casefold()]
            if not named:
                hint = _did_you_mean(str(choice), [link[0] for link in links])
                raise fail(comment.file, comment.line, f"browser comment: no link {choice!r}{hint}")
            text, href = named[0]
        try:
            url = resolve_link(href, block.file)
        except LinkError as error:
            raise fail(comment.file, comment.line, f"browser comment: {error}") from error
        self.show_view(
            comment, {"browser": {"url": url, **options}}, f"browser comment: opens {text!r} ({url})"
        )

    def show_view(self, block: Block, action: dict[str, Any], what: str) -> None:
        """A browser view or slide from the next paragraph on, until the next command or heading."""
        self.flush()  # the page appears with its paragraph, not with the narration before
        self.pending_view(block, action, what)

    def pending_view(self, block: Block, action: dict[str, Any], what: str) -> None:
        """Show ``action`` with the text around it, up to the next block."""
        self.overlays.append((None, action))
        self.unassigned.append((block, what))
        self.image = True

    def slide_comment(self, block: Comment, body: str) -> None:
        options = _options(body, block, "slide", SLIDE_KEYS)
        if "html" not in options:
            self.slide = (block, options)
            return
        name = str(options.pop("html"))
        path = block.file.parent / name
        if not path.is_file():
            raise fail(block.file, block.line, f"slide comment: file not found: {name}")
        html_url = _embed("text/html", path.read_bytes(), block, name)
        self.show_view(block, {"slide": {**options, "html": html_url}}, f"slide comment: shows {name}")

    def take_slide(self) -> dict[str, Any] | None:
        """The pending slide comment's options, if any."""
        options = self.slide[1] if self.slide is not None else None
        self.slide = None
        return options

    def no_block(self, pending: tuple[Comment, dict[str, Any]], kind: str, expected: str) -> None:
        comment = pending[0]
        raise fail(comment.file, comment.line, f"{kind} comment: the next block is not {expected}")

    def show_image(self, block: Image) -> None:
        """Show the image as a slide while the text around it is spoken, up to the next block."""
        look = self.take_slide() or {}
        if not self.entry.images:
            self.note(block, None, "image: left out (images: false)")
            return
        if "://" in block.src or block.src.startswith("data:"):
            self.note(block, None, "image: left out (not a local file)")
            return
        path = block.file.parent / block.src.split("#")[0].split("?")[0]
        mime = SLIDE_IMAGE_TYPES.get(path.suffix.lower())
        if mime is None:
            self.note(block, None, f"image: left out ({path.suffix or 'no'} files are not shown)")
            return
        if not path.is_file():
            raise fail(block.file, block.line, f"image not found: {block.src}")
        data = f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"
        self.pending_view(block, {"slide": {**look, "image": data}}, "image: shown as a slide")

    def show_diagram(self, block: Code) -> None:
        """A Mermaid diagram, shown like an image; the renderer draws it."""
        look = self.take_slide() or {}
        if not self.entry.images:
            self.note(block, None, "mermaid block: left out (images: false)")
            return
        slide = {**look, "mermaid": block.content}
        self.pending_view(block, {"slide": slide}, "mermaid block: shown as a slide")

    def pause(self, block: Comment, body: str) -> None:
        """End the scene here; with a duration, a silent scene follows.

        While a table with pages is shown, the next page appears here instead.
        """
        ms = _duration(body, block, "pause comment") if body else 0
        page = self.pages.pop(0) if self.pages else None
        self.flush(pages=False)
        if page is not None:
            if ms:
                self.emit(block, {"id": self.next_id(None), "actions": [{"slide": page}, {"hold": ms}]})
            self.pending_view(block, {"slide": page}, f"pause comment: table page {page['page']}")
            return
        if not ms:
            self.note(block, None, "pause comment: the scene ends here")
            return
        scene_id = self.next_id(None)
        self.emit(block, {"id": scene_id, "actions": [{"hold": ms}]})
        self.note(block, scene_id, f"pause comment: {ms} ms of silence")

    def table_comment(self, block: Comment, body: str) -> None:
        options = _options(body, block, "table", TABLE_KEYS)
        if "say" in options and not isinstance(options["say"], str):
            raise fail(block.file, block.line, "table comment: say must be a text such as '{Name}: {Value}'")
        if "pause" in options:
            options["pause"] = _duration(options["pause"], block, "table comment: pause")
        self.table = (block, options)

    def show_table(self, block: Table) -> None:
        """A slide of the table, with a slide or table comment; left out otherwise."""
        look = self.take_slide()
        if self.table is None and look is None:
            self.note(block, None, "table: not part of the video")
            return
        table = {"header": list(block.header_source), "rows": [list(row) for row in block.rows_source]}
        if self.table is None:
            assert look is not None
            self.show_pages(block, look, table)
            return
        comment, options = self.table
        self.table = None
        if not block.rows:
            raise fail(comment.file, comment.line, "table comment: the table has no rows")
        look = {key: options[key] for key in SLIDE_KEYS if key in options} | (look or {})
        template = options.get("say")
        if template is not None:
            _check_fields(template, block.header, comment)
        pause = options.get("pause")
        self.flush()
        for number, (row, line) in enumerate(zip(block.rows, block.row_lines, strict=True), 1):
            source = Block(block.file, line)
            self.overlays.append((None, {"slide": {**look, "table": table, "highlight": number}}))
            text = row_text(block.header, row, template)
            if text:
                self.spoken.append(text)
            self.unassigned.append((source, f"table row {number}: " + ("spoken" if text else "empty")))
            actions: list[dict[str, Any]] = [{"hold": pause}] if pause else []
            if not text:
                actions.append({"hold": IMAGE_HOLD_MS})
            extra = {"narration_start": "after_actions"} if pause and text else {}
            self.scene(source, self.next_id(None), actions, extra)

    def show_pages(self, block: Table, look: dict[str, Any], table: dict[str, Any]) -> None:
        """A table shown, not read: its first page now, the next ones at ``pause`` comments."""
        per_page = look.get("rows")
        count = -(-len(block.rows) // per_page) if isinstance(per_page, int) and per_page > 0 else 1
        if count == 1:
            self.pending_view(block, {"slide": {**look, "table": table}}, "table: shown as a slide")
            return
        pages = [{**look, "table": table, "page": number} for number in range(1, count + 1)]
        self.pending_view(block, {"slide": pages[0]}, f"table: shown as a slide, page 1 of {count}")
        self.pages, self.pages_block = pages[1:], block

    def code(self, block: Code) -> None:
        options = set(block.options)
        if unknown := sorted(options - set(BLOCK_OPTIONS)):
            raise fail(
                block.file,
                block.line,
                f"unknown narratty option {unknown[0]!r}; expected one of {', '.join(BLOCK_OPTIONS)}",
            )
        if self.image and (block.lang == "console" or block.lang in SHELL_LANGS or block.title):
            self.flush()  # an image never covers commands
        if block.lang == "mermaid":
            if options:
                raise fail(
                    block.file, block.line, f"{sorted(options)[0]!r} only applies to shell and console blocks"
                )
            self.show_diagram(block)
        elif block.lang == "console" or block.lang in SHELL_LANGS:
            self.commands(block, options)
        elif block.title:
            self.file(block, options)
        else:
            self.note(block, None, f"{block.lang or 'code'} block: left out (no title)")

    def commands(self, block: Code, options: set[str]) -> None:
        commands = (
            console_commands(block.content) if block.lang == "console" else split_commands(block.content)
        )
        if "no-run" in options:
            actions = [action for command in commands for action in _typed(command.text)]
        else:
            _check_placeholders(commands, block, 1)
            actions = _runs(commands)
        extra = {"expect_exit": "failure"} if "expect-failure" in options else {}
        scene_id = self.next_id(block)
        how = "typed, not run" if "no-run" in options else "run"
        if "hidden" in options:
            self.emit(block, {"id": scene_id, "hidden": True, "actions": actions, **extra})
            how += ", not shown"
        else:
            self.scene(block, scene_id, actions, extra)
        self.note(block, scene_id, f"{block.lang} block: {len(commands)} command(s), {how}")

    def file(self, block: Code, options: set[str]) -> None:
        assert block.title is not None
        if extra := sorted(options - {"hidden"}):
            raise fail(block.file, block.line, f"{extra[0]!r} only applies to shell and console blocks")
        scene_id = self.next_id(block)
        write = {"run": write_file(block.title, block.content)}
        self.emit(
            block,
            {"id": f"{scene_id}-write", "hidden": True, "typing_speed_ms": 1, "actions": [write, _wait()]},
        )
        if "hidden" in options:
            self.note(block, f"{scene_id}-write", f"{block.lang} block: writes {block.title}, not shown")
            return
        actions: list[dict[str, Any]] = []
        if self.entry.file_titles:
            actions.append({"overlay": {"text": block.title, "style": "file"}})
        actions += [{"run": f"cat {shlex.quote(block.title)}"}, _wait()]
        self.scene(block, scene_id, actions, {})
        self.note(block, scene_id, f"{block.lang} block: writes and shows {block.title}")

    # ── scenes ──

    def flush(self, *, pages: bool = True) -> None:
        """Narration after the last block of a section: a scene without actions.

        Table pages no ``pause`` comment brought up yet follow as silent scenes.
        """
        if self.spoken or self.image:
            first = self.unassigned[0][0] if self.unassigned else None
            assert first is not None
            hold = [] if self.spoken else [{"hold": IMAGE_HOLD_MS}]
            self.scene(first, self.next_id(None), hold, {})
        while pages and self.pages:
            assert self.pages_block is not None
            page = self.pages.pop(0)
            scene_id = self.next_id(None)
            self.emit(
                self.pages_block, {"id": scene_id, "actions": [{"slide": page}, {"hold": IMAGE_HOLD_MS}]}
            )
            self.note(self.pages_block, scene_id, f"table: page {page['page']}, silent")

    def scene(
        self, block: Block, scene_id: str, actions: list[dict[str, Any]], extra: dict[str, Any]
    ) -> None:
        """A visible scene: takes the pending narration and overlays."""
        data: dict[str, Any] = {"id": scene_id}
        if self.spoken:
            data["narration"] = " ".join(self.spoken)
        lead = [action for _, action in self.overlays]
        if crumb := self.breadcrumb():
            lead.insert(0, {"overlay": {"text": crumb, "style": "breadcrumb"}})
        data["actions"] = actions
        data |= self.defaults | extra
        for source, what in self.unassigned:
            self.note(source, scene_id, what)
        self.spoken, self.unassigned, self.overlays, self.image = [], [], [], False
        self.emit(block, data, lead)

    def emit(self, block: Block, data: dict[str, Any], lead: Sequence[dict[str, Any]] = ()) -> None:
        """Add a scene; ``lead`` are overlays shown before the block's own actions."""
        if isinstance(block, Code) and block.id and block.id in self.entry.overrides:
            data = self.override(block.id, data)
        data["actions"] = [*lead, *data.get("actions", [])]
        if not data["actions"]:
            data.pop("actions", None)
        self.scenes.append(ExpandedScene(data, block.file, block.line))

    def override(self, block_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if data["id"].endswith("-write") and data["id"] != f"{self.prefix}-{id_part(block_id)}":
            return data  # a file block's hidden write; the override applies to its visible scene
        self.used.add(block_id)
        change = self.entry.overrides[block_id]
        keys = change.model_dump(exclude_none=True, exclude={"before", "after"})
        before = [
            action.model_dump(exclude_none=True, exclude_defaults=True) or _bare(action)
            for action in change.before
        ]
        after = [
            action.model_dump(exclude_none=True, exclude_defaults=True) or _bare(action)
            for action in change.after
        ]
        return data | keys | {"actions": before + data.get("actions", []) + after}

    def breadcrumb(self) -> str:
        settings = self.entry.heading_overlays
        if settings is None or not settings.breadcrumb or not self.trail:
            return ""
        return breadcrumb_text([self.trail[level] for level in sorted(self.trail)], settings)

    def next_id(self, block: Code | None) -> str:
        if block is not None and block.id:
            return f"{self.prefix}-{id_part(block.id)}"
        self.count += 1
        section = "" if self.section == self.prefix else self.section  # no "install-install-1"
        return "-".join(part for part in (self.prefix, section, str(self.count)) if part)

    def note(self, block: Block, scene_id: str | None, what: str) -> None:
        self.notes.append(Note(block.file, block.line, scene_id, what))

    def check_overrides(self, blocks: list[Block]) -> None:
        ids = sorted({block.id for block in blocks if isinstance(block, Code) and block.id})
        for block_id in self.entry.overrides:
            if block_id not in self.used:
                where = "in the selected sections" if block_id in ids else "in the doc"
                raise EntryError(
                    ("overrides", block_id), f"no block {block_id!r} {where}{_did_you_mean(block_id, ids)}"
                )


def _kind(block: Block) -> str:
    if isinstance(block, Image):
        return "image"
    if isinstance(block, Table):
        return "table"
    return "paragraph" if isinstance(block, Text) else f"{getattr(block, 'lang', '') or 'code'} block"


def _visual(block: Block) -> bool:
    """Whether a slide comment can show ``block``."""
    return isinstance(block, (Table, Image)) or (isinstance(block, Code) and block.lang == "mermaid")


def _bare(action: Any) -> dict[str, Any]:
    """An action whose fields are all defaults (``enter``, ``diff``)."""
    return {next(iter(type(action).model_fields)): True}


def _yaml_value(text: str, block: Block, kind: str) -> Any:
    from ruamel.yaml import YAML
    from ruamel.yaml.error import YAMLError

    try:
        value = YAML(typ="safe").load(text)
    except YAMLError as error:
        raise fail(block.file, block.line, f"{kind} comment: invalid YAML: {error}") from error
    return value


def _duration(value: Any, block: Block, what: str) -> int:
    ms = to_ms(value.strip() if isinstance(value, str) else value)
    if not isinstance(ms, int) or isinstance(ms, bool) or ms < 0:
        raise fail(
            block.file, block.line, f"{what}: expected a duration such as 800ms or 1.5s, got {value!r}"
        )
    return ms


def _embed(mime: str, data: bytes, block: Block, name: str) -> str:
    url = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    if len(url) > MAX_URL_CHARS:
        raise fail(
            block.file, block.line, f"{name} is too large to embed (Chromium loads data: URLs up to 2 MB)"
        )
    return url


def _options(body: str, block: Comment, kind: str, keys: Sequence[str]) -> dict[str, Any]:
    """The mapping a comment takes, with only ``keys``."""
    options = _yaml_value(body, block, kind) if body else {}
    if not isinstance(options, dict):
        raise fail(block.file, block.line, f"{kind} comment: expected a mapping such as {{{keys[0]}: ...}}")
    if unknown := sorted(set(options) - set(keys)):
        raise fail(
            block.file,
            block.line,
            f"{kind} comment: unknown key {unknown[0]!r}; expected one of {', '.join(keys)}",
        )
    return options


# ── tables ─────────────────────────────────────────────────────────────────────────────


def _column(name: str, header: Sequence[str]) -> int | None:
    name = name.strip()
    if name in header:
        return header.index(name)
    folded = [title.casefold() for title in header]
    return folded.index(name.casefold()) if name.casefold() in folded else None


def _check_fields(template: str, header: Sequence[str], comment: Comment) -> None:
    for match in _FIELD.finditer(template):
        if _column(match[1], header) is None:
            raise fail(
                comment.file,
                comment.line,
                f"table comment: no column {match[1]!r}{_did_you_mean(match[1], list(header))}",
            )


def row_text(header: Sequence[str], row: Sequence[str], template: str | None) -> str:
    """How a table row is spoken: ``template`` filled in, else ``Header: cell.`` per cell."""
    if template is not None:

        def cell(match: re.Match[str]) -> str:
            index = _column(match[1], header)
            return row[index] if index is not None and index < len(row) else ""

        return " ".join(_FIELD.sub(cell, template).split())
    parts = []
    for number, value in enumerate(row):
        if not value:
            continue
        name = header[number] if number < len(header) else ""
        part = f"{name}: {value}" if name else value
        parts.append(part if part.endswith(SENTENCE_END) else part + ".")
    return " ".join(parts)


# ── actions ───────────────────────────────────────────────────────────────────


def _wait() -> dict[str, Any]:
    return {"wait": {"prompt": True}}


def _runs(commands: Sequence[Command]) -> list[dict[str, Any]]:
    """Run each command and wait until it has finished (``run`` does not wait)."""
    return [action for command in commands for action in ({"run": command.text}, _wait())]


def _typed(command: str) -> list[dict[str, Any]]:
    """Type a command, let it be read, then cancel it with Ctrl+C."""
    return [{"type_command": command}, {"hold": NO_RUN_HOLD_MS}, {"ctrl_sequence": "C-c"}]


def _check_placeholders(commands: Sequence[Command], block: Block, first_line: int) -> None:
    for command in commands:
        if command.placeholders:
            name = command.placeholders[0]
            variable = re.sub(r"\W", "_", name.strip("<>")).upper()
            raise fail(
                block.file,
                block.line + first_line + command.offset,
                f"{name} is a placeholder; write it as ${variable} and set it in sandbox.env, "
                "sandbox.env_passthrough or a hidden comment, or mark the block no-run",
            )


def console_commands(content: str) -> list[Command]:
    """``$ `` lines of a console block, with their ``> `` continuation lines."""
    raw: list[tuple[str, int]] = []
    for offset, line in enumerate(content.splitlines()):
        if line.startswith("$ ") or line == "$":
            raw.append((line[2:], offset))
        elif line.startswith("> ") and raw:
            raw[-1] = (raw[-1][0] + "\n" + line[2:], raw[-1][1])
    commands = []
    for text, offset in raw:
        command = clean_command(text)
        if command.text.strip():
            commands.append(Command(command.text, offset, command.placeholders))
    return commands


def write_file(path: str, content: str) -> str:
    """A shell command that writes ``content`` to ``path`` (creating its directory)."""
    lines = content.removesuffix("\n").split("\n")
    delimiter = "NARRATTY_EOF"
    while delimiter in lines:
        delimiter += "_"
    folder = posixpath.dirname(path)
    mkdir = f"mkdir -p {shlex.quote(folder)} && " if folder else ""
    return f"{mkdir}cat > {shlex.quote(path)} <<'{delimiter}'\n" + "\n".join(lines) + f"\n{delimiter}"


def breadcrumb_text(parts: list[str], settings: HeadingOverlays) -> str:
    """``parts`` joined; when too long, middle parts become ``…``, then the last is cut."""
    shown = list(parts)
    for index in range(1, len(parts) - 1):
        if len(settings.separator.join(shown)) <= settings.max_length:
            break
        shown[index] = "…"
    shown = [part for number, part in enumerate(shown) if part != "…" or shown[number - 1 : number] != ["…"]]
    text = settings.separator.join(shown)
    if len(text) > settings.max_length:
        text = text[: settings.max_length - 1].rstrip() + "…"
    return text


def id_part(text: str) -> str:
    """``text`` as part of a scene id: ASCII, lower case, ``-`` between words."""
    ascii_text = unicodedata.normalize("NFKD", text.replace("ß", "ss")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9_]+", "-", ascii_text.lower()).strip("-_")
