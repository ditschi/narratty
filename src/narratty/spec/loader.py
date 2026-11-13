"""Load ``.narratty.yaml`` into a :class:`Spec`, reporting errors with file positions."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from packaging.version import Version
from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import MarkedYAMLError

from narratty import __version__
from narratty.errors import ExitCode, NarrattyError
from narratty.spec.model import ACTION_KEYS, MarkdownEntry, MarkdownNarration, Spec, parse_requirement

if TYPE_CHECKING:
    from narratty.spec.markdown import ExpandedScene

SPEC_SUFFIXES = (".narratty.yaml", ".narratty.yml")
MARKDOWN_SUFFIXES = (".md", ".markdown")


def is_markdown(path: Path) -> bool:
    """Whether ``path`` is a Markdown doc, built on its own with the spec it implies."""
    return path.suffix.lower() in MARKDOWN_SUFFIXES


@dataclass(frozen=True)
class Issue:
    """One problem found in a spec, with a 1-based position when known.

    ``file`` is set when the problem is in another file than the spec (a Markdown doc).
    """

    path: str
    message: str
    line: int | None = None
    column: int | None = None
    file: Path | None = None

    def render(self, file: Path) -> str:
        """``file:line:col: path: message`` (position omitted when unknown)."""
        where = str(self.file or file)
        if self.line is not None:
            where += f":{self.line}:{self.column or 1}"
        prefix = f"{self.path}: " if self.path else ""
        return f"{where}: {prefix}{self.message}"


class SpecError(NarrattyError):
    """The spec could not be read or failed validation."""

    exit_code = ExitCode.VALIDATION

    def __init__(self, file: Path, issues: list[Issue]) -> None:
        self.file = file
        self.issues = issues
        count = len(issues)
        summary = f"{file}: {count} problem{'s' if count != 1 else ''}\n" + "\n".join(
            f"  {issue.render(file)}" for issue in issues
        )
        super().__init__(summary, hint=_hint(issues))


SCHEMA_HINT = "Run `narratty schema` for the full list of keys."
YAML_HINT = (
    "Quote YAML values that contain `{`, `}`, `[`, `:` followed by a space, `#` or a leading "
    '`/`, `*` or `&`: `{title: "GET /orders/{id}"}`.'
)


def _hint(issues: list[Issue]) -> str | None:
    """How to fix ``issues``: quoting for YAML that does not parse, else the schema."""
    if issues and all("invalid YAML" in issue.message for issue in issues):
        return YAML_HINT
    if issues and all(issue.file is not None and issue.file.suffix in (".md", ".markdown") for issue in issues):
        return None  # a Markdown doc: the message says what to write, the schema does not
    return SCHEMA_HINT


def _field_names(model: type[BaseModel], seen: set[type[BaseModel]] | None = None) -> set[str]:
    """Every key used anywhere in the spec schema (for "did you mean" hints)."""
    seen = seen if seen is not None else set()
    if model in seen:
        return set()
    seen.add(model)
    names = set(model.model_fields)
    for field in model.model_fields.values():
        for candidate in _nested_models(field.annotation):
            names |= _field_names(candidate, seen)
    return names


def _nested_models(annotation: Any) -> list[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    found: list[type[BaseModel]] = []
    for arg in getattr(annotation, "__args__", ()) or ():
        found += _nested_models(arg)
    for meta in getattr(annotation, "__metadata__", ()) or ():
        found += _nested_models(meta)
    return found


_KNOWN_KEYS = sorted(_field_names(Spec) | _field_names(MarkdownEntry))


def format_path(loc: tuple[int | str, ...]) -> str:
    out = ""
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


def position(data: Any, loc: tuple[int | str, ...]) -> tuple[int | None, int | None]:
    """Best-effort 1-based (line, column) of ``loc`` inside ruamel round-trip data."""
    line: int | None = None
    column: int | None = None
    node = data
    for part in loc:
        try:
            if isinstance(node, CommentedMap) and part in node:
                row, col = node.lc.key(part)
                node = node[part]
            elif isinstance(node, CommentedSeq) and isinstance(part, int) and part < len(node):
                row, col = node.lc.item(part)
                node = node[part]
            else:
                break
        except (KeyError, TypeError, AttributeError):  # pragma: no cover - defensive
            break
        line, column = row + 1, col + 1
    return line, column


def _message(error: Any) -> str:
    kind = error["type"]
    key = error["loc"][-1] if error["loc"] else ""
    if kind == "extra_forbidden":
        message = f"unknown key {key!r}"
        match = difflib.get_close_matches(str(key), _KNOWN_KEYS, n=1)
        return f"{message} (did you mean {match[0]!r}?)" if match else message
    if kind == "invalid_action":
        given = error.get("input")
        if isinstance(given, dict) and len(given) == 1:
            name = str(next(iter(given)))
            match = difflib.get_close_matches(name, ACTION_KEYS, n=1)
            hint = f" (did you mean {match[0]!r}?)" if match else ""
            return f"unknown action {name!r}{hint}"
        return str(error["msg"])
    if kind == "missing":
        return f"missing required key {key!r}"
    msg = str(error["msg"])
    return msg.removeprefix("Value error, ")


def _strip_union_tags(loc: tuple[int | str, ...]) -> tuple[int | str, ...]:
    """Drop the discriminator tag Pydantic inserts for action unions (``…, 'hold', 'hold'``)."""
    out: list[int | str] = []
    for part in loc:
        if out and part == out[-1] and isinstance(part, str):
            continue
        out.append(part)
    return tuple(out)


def to_plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): to_plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_plain(v) for v in value]
    if isinstance(value, str):
        return str(value)
    return value


def _bullet(line: str) -> bool:
    """True for a line that uses a Markdown bullet (``* item``) as a list marker."""
    return line.lstrip().startswith("* ")


def parse_spec(text: str, file: Path) -> Spec:
    """Parse YAML ``text`` (from ``file``) into a validated :class:`Spec`."""
    return parse_document(text, file)[0]


def check_required_version(data: dict[Any, Any], file: Path, installed: str | None = None) -> None:
    """Fail early when ``requires.narratty`` excludes this narratty.

    Runs before validation, so a spec for a newer narratty reports the version it needs
    instead of its unknown keys. Untagged source builds (``0.0.0+unknown``) are not checked.
    """
    requires = data.get("requires")
    wanted = requires.get("narratty") if isinstance(requires, dict) else None
    current = installed or __version__
    if not isinstance(wanted, str) or current.startswith("0.0.0"):
        return
    try:
        specifier = parse_requirement(wanted)
    except ValueError:
        return  # reported with its position by model validation
    if not specifier.contains(Version(current), prereleases=True):
        line, column = position(data, ("requires", "narratty"))
        message = f"this spec needs narratty {wanted}, but {current} is installed; upgrade narratty"
        raise SpecError(file, [Issue("requires.narratty", message, line, column)])


class Document(NamedTuple):
    """A validated spec with the YAML as written and where each of its scenes came from."""

    spec: Spec
    data: dict[Any, Any]
    origins: list[int | ExpandedScene]
    """Per scene of ``spec``: its index in ``data["scenes"]``, or the Markdown it came from."""


def _load_yaml(text: str, file: Path) -> dict[Any, Any]:
    if is_markdown(file):
        return _implied(text, file)
    yaml = YAML(typ="rt")
    try:
        data = yaml.load(text)
    except MarkedYAMLError as error:
        mark = error.problem_mark
        line = mark.line + 1 if mark is not None else None
        column = mark.column + 1 if mark is not None else None
        message = f"invalid YAML: {error.problem}"
        lines = text.splitlines()
        if line is not None and line <= len(lines) and _bullet(lines[line - 1]):
            message = "invalid YAML: list items start with '- ', not '* ' ('*' starts an alias in YAML)"
        raise SpecError(file, [Issue("", message, line, column)]) from error
    if not isinstance(data, dict):
        raise SpecError(file, [Issue("", "the spec must be a YAML mapping with a 'scenes' list", 1, 1)])
    return data


def _implied(text: str, doc: Path) -> dict[Any, Any]:
    """The spec of a doc built on its own; ``text`` is its spec comment's YAML."""
    from narratty.spec.markdown import implied_spec

    try:
        data = YAML(typ="rt").load(text) if text.strip() else CommentedMap()
    except MarkedYAMLError as error:
        mark = error.problem_mark
        line, column = (mark.line + 1, mark.column + 1) if mark is not None else (None, None)
        raise SpecError(
            doc, [Issue("", f"spec comment: invalid YAML: {error.problem}", line, column)]
        ) from error
    if not isinstance(data, CommentedMap):
        line = len(text) - len(text.lstrip("\n")) + 1
        raise SpecError(doc, [Issue("", "spec comment: expected a YAML mapping of spec keys", line)])
    return implied_spec(data, doc)


def _validation_issues(error: ValidationError, data: Any, prefix: tuple[int | str, ...] = ()) -> list[Issue]:
    issues = []
    for item in error.errors():
        loc = (*prefix, *_strip_union_tags(tuple(item["loc"])))
        issues.append(Issue(format_path(loc), _message(item), *position(data, loc)))
    return issues


def _expand_scenes(
    raw_scenes: list[Any], data: dict[Any, Any], file: Path
) -> tuple[list[Any], list[int | ExpandedScene]]:
    """``raw_scenes`` with each ``markdown`` entry replaced by its scenes."""
    from narratty.spec.markdown import EntryError, expand_entry

    default: MarkdownNarration = "none" if data.get("narration") == "none" else "all"
    scenes: list[Any] = []
    origins: list[int | ExpandedScene] = []
    issues: list[Issue] = []
    for index, raw in enumerate(raw_scenes):
        if not (isinstance(raw, dict) and "markdown" in raw):
            scenes.append(to_plain(raw))
            origins.append(index)
            continue
        try:
            entry = MarkdownEntry.model_validate(to_plain(raw))
        except ValidationError as error:
            issues += _validation_issues(error, data, ("scenes", index))
            continue
        path = file.parent / entry.markdown
        if not path.is_file():
            at: tuple[int | str, ...] = ("scenes", index, "markdown")
            issues.append(Issue(format_path(at), f"no such file: {path}", *position(data, at)))
            continue
        try:
            expanded = expand_entry(entry, path, entry.narration or default)
        except SpecError as error:
            issues += [issue if issue.file else _in_file(issue, error.file) for issue in error.issues]
            continue
        except EntryError as error:
            at = ("scenes", index, *error.loc)
            issues.append(Issue(format_path(at), error.message, *position(data, at)))
            continue
        scenes += [scene.data for scene in expanded]
        origins += expanded
    if issues:
        raise SpecError(file, issues)
    return scenes, origins


def _in_file(issue: Issue, file: Path) -> Issue:
    return Issue(issue.path, issue.message, issue.line, issue.column, file)


def _scene_issue(item: Any, origins: list[int | ExpandedScene], data: Any) -> Issue:
    """An issue of the expanded spec, positioned where the scene was written."""
    loc = _strip_union_tags(tuple(item["loc"]))
    origin = origins[loc[1]] if len(loc) > 1 and loc[0] == "scenes" and isinstance(loc[1], int) else None
    if isinstance(origin, int):
        loc = ("scenes", origin, *loc[2:])
    elif origin is not None:
        scene_id = origin.data.get("id")
        rest = format_path(loc[2:])
        path = f"scene {scene_id!r}" + (f": {rest}" if rest else "")
        return Issue(path, _message(item), origin.line, None, origin.file)
    return Issue(format_path(loc), _message(item), *position(data, loc))


def parse_document(text: str, file: Path) -> Document:
    """Like :func:`parse_spec`, plus the YAML as written (with line numbers).

    ``markdown`` entries in ``scenes`` are expanded into the scenes of their doc.
    """
    data = _load_yaml(text, file)
    check_required_version(data, file)
    plain = to_plain(data)
    origins: list[int | ExpandedScene] = []
    if isinstance(data.get("scenes"), list):
        plain["scenes"], origins = _expand_scenes(data["scenes"], data, file)
    try:
        return Document(Spec.model_validate(plain), data, origins)
    except ValidationError as error:
        issues = [_scene_issue(item, origins, data) for item in error.errors()]
        raise SpecError(file, issues) from error


def read_spec_text(path: Path) -> str:
    """The text of the spec at ``path``; for a Markdown doc, the YAML of its spec comment."""
    if is_markdown(path):
        from narratty.spec.markdown import spec_comment_text

        return spec_comment_text(path)
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise SpecError(path, [Issue("", f"cannot read file: {error.strerror or error}")]) from error


def load_spec(path: Path) -> Spec:
    """Read and validate the spec at ``path``."""
    return parse_spec(read_spec_text(path), path)
