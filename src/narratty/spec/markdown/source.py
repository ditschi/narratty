"""Line-level preprocessing: snippet inclusion and content tab selection.

Both work on lines that remember their file and line number, so everything parsed
later can be reported where it was written, also inside an included snippet.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from narratty.spec.loader import Issue, SpecError

# pymdownx.snippets: `--8<-- "path"`, optionally `path:start:end` (1-based, inclusive).
_SNIPPET = re.compile(
    r"^(?P<indent>[ \t]*)(?P<escape>;?)-+8<-+[ \t]+(?P<q>[\"'])(?P<target>.*?)(?P=q)[ \t]*$"
)
_SNIPPET_BLOCK = re.compile(r"^[ \t]*-+8<-+[ \t]*$")
_LINES = re.compile(r"^(?P<path>.*?)(?::(?P<start>\d*)(?::(?P<end>\d*))?)?$")
_TAB = re.compile(r"^(?P<indent>[ \t]*)===\+?[ \t]+\"(?P<label>[^\"]*)\"[ \t]*$")
_FENCE = re.compile(r"^[ \t]*(?P<marker>`{3,}|~{3,})")
_MAX_DEPTH = 10


@dataclass(frozen=True)
class Line:
    """One line of text and where it was written (1-based)."""

    text: str
    file: Path
    number: int


def fail(file: Path, line: int | None, message: str) -> SpecError:
    """An error at ``file:line`` (raise it)."""
    return SpecError(file, [Issue("", message, line, 1 if line else None, file)])


def read_source(path: Path, tabs: Sequence[str] = ()) -> list[Line]:
    """The lines of the Markdown file at ``path`` with snippets inserted and one tab per set."""
    lines = _with_snippets(_read(path, None), _snippet_bases(path), ())
    return select_tabs(lines, tabs)


def _read(path: Path, at: Line | None) -> list[Line]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        where = at.file if at else path
        raise fail(
            where, at.number if at else None, f"cannot read {path}: {error.strerror or error}"
        ) from error
    return [Line(text, path, number) for number, text in enumerate(text.splitlines(), start=1)]


# ── snippets ──────────────────────────────────────────────────────────────────


def _snippet_bases(path: Path) -> list[Path]:
    """Where snippet paths are looked up: ``base_path`` from mkdocs.yml, else the repo root."""
    from ruamel.yaml import YAML
    from ruamel.yaml.error import YAMLError

    for folder in path.resolve().parents:
        config = folder / "mkdocs.yml"
        if config.is_file():
            try:
                data = YAML(typ="rt").load(config.read_text(encoding="utf-8"))
            except (OSError, YAMLError):
                return [folder]
            return [folder / base for base in _configured_bases(data)] or [folder]
        if (folder / ".git").exists():
            return [folder]
    return [path.parent]


def _configured_bases(data: object) -> list[str]:
    extensions = data.get("markdown_extensions") if isinstance(data, dict) else None
    for extension in extensions if isinstance(extensions, list) else []:
        if isinstance(extension, dict) and isinstance(options := extension.get("pymdownx.snippets"), dict):
            bases = options.get("base_path", ["."])
            return [str(base) for base in ([bases] if isinstance(bases, str) else bases)]
    return []


def _with_snippets(lines: list[Line], bases: list[Path], stack: tuple[Path, ...]) -> list[Line]:
    out: list[Line] = []
    for line in lines:
        if _SNIPPET_BLOCK.match(line.text):
            raise fail(
                line.file,
                line.number,
                "block snippets (--8<-- on its own line) are not supported; "
                'include each file with --8<-- "path"',
            )
        match = _SNIPPET.match(line.text)
        if match is None:
            out.append(line)
        elif match["escape"]:
            out.append(Line(line.text.replace(";", "", 1), line.file, line.number))
        else:
            out += _snippet(match["target"], match["indent"], line, bases, stack)
    return out


def _snippet(target: str, indent: str, at: Line, bases: list[Path], stack: tuple[Path, ...]) -> list[Line]:
    if "://" in target:
        raise fail(at.file, at.number, f"URL snippets are not supported: {target}")
    match = _LINES.match(target)
    assert match is not None  # the pattern matches any string
    candidates = [base / match["path"] for base in bases]
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        hint = " (named sections are not supported)" if ":" in target and match["path"] != target else ""
        raise fail(at.file, at.number, f"snippet not found: {target}{hint}")
    if path.resolve() in stack or len(stack) >= _MAX_DEPTH:
        raise fail(at.file, at.number, f"snippet includes itself: {target}")
    lines = _read(path, at)
    start = int(match["start"]) if match["start"] else 1
    end = int(match["end"]) if match["end"] else len(lines)
    lines = [
        Line(indent + line.text if line.text else "", line.file, line.number)
        for line in lines[start - 1 : end]
    ]
    return _with_snippets(lines, bases, (*stack, path.resolve()))


# ── content tabs ──────────────────────────────────────────────────────────────


def select_tabs(lines: list[Line], preferred: Sequence[str]) -> list[Line]:
    """Keep one tab of each ``=== "label"`` set, dedented; the other lines become blank.

    Line numbers stay as they are. The kept tab is the first label in ``preferred`` that
    the set has, otherwise its first tab.
    """
    out: list[Line] = []
    fence: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if (opener := _FENCE.match(line.text)) is not None:
            marker = opener["marker"]
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and not line.text.strip()[len(marker) :]:
                fence = None
        if fence is not None or (tab := _TAB.match(line.text)) is None:
            out.append(line)
            index += 1
            continue
        tabs, index = _tab_set(lines, index, len(tab["indent"]))
        labels = [label for label, _, _ in tabs]
        chosen = next((labels.index(label) for label in preferred if label in labels), 0)
        for number, (_, header, body) in enumerate(tabs):
            out.append(_blank(header))
            if number == chosen:
                out += select_tabs([_dedent(body_line, len(tab["indent"])) for body_line in body], preferred)
            else:
                out += [_blank(body_line) for body_line in body]
    return out


def _tab_set(lines: list[Line], index: int, indent: int) -> tuple[list[tuple[str, Line, list[Line]]], int]:
    """The tabs starting at ``index`` (label, header line, body lines) and the index after them."""
    tabs: list[tuple[str, Line, list[Line]]] = []
    while index < len(lines) and (tab := _TAB.match(lines[index].text)) and len(tab["indent"]) == indent:
        header = lines[index]
        index += 1
        body: list[Line] = []
        while index < len(lines) and (
            not lines[index].text.strip() or _indent(lines[index].text) >= indent + 4
        ):
            body.append(lines[index])
            index += 1
        tabs.append((tab["label"], header, body))
    return tabs, index


def _indent(text: str) -> int:
    return len(text) - len(text.lstrip(" "))


def _dedent(line: Line, indent: int) -> Line:
    text = line.text[:indent] + line.text[indent + 4 :] if line.text.strip() else ""
    return Line(text, line.file, line.number)


def _blank(line: Line) -> Line:
    return Line("", line.file, line.number)
