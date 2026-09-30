"""Load ``.narratty.yaml`` into a :class:`Spec`, reporting errors with file positions."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import MarkedYAMLError

from narratty.errors import ExitCode, NarrattyError
from narratty.spec.model import ACTION_KEYS, Spec

SPEC_SUFFIXES = (".narratty.yaml", ".narratty.yml")


@dataclass(frozen=True)
class Issue:
    """One problem found in a spec, with a 1-based position when known."""

    path: str
    message: str
    line: int | None = None
    column: int | None = None

    def render(self, file: Path) -> str:
        """``file:line:col: path: message`` (position omitted when unknown)."""
        where = str(file)
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
        super().__init__(summary, hint="Run `narratty schema` for the full list of keys.")


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


_KNOWN_KEYS = sorted(_field_names(Spec))


def _format_path(loc: tuple[int | str, ...]) -> str:
    out = ""
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


def _position(data: Any, loc: tuple[int | str, ...]) -> tuple[int | None, int | None]:
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


def _to_plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_plain(v) for v in value]
    if isinstance(value, str):
        return str(value)
    return value


def _bullet(line: str) -> bool:
    """True for a line that uses a Markdown bullet (``* item``) as a list marker."""
    return line.lstrip().startswith("* ")


def parse_spec(text: str, file: Path) -> Spec:
    """Parse YAML ``text`` (from ``file``) into a validated :class:`Spec`."""
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
    try:
        return Spec.model_validate(_to_plain(data))
    except ValidationError as error:
        issues = []
        for item in error.errors():
            loc = _strip_union_tags(tuple(item["loc"]))
            line, column = _position(data, loc)
            issues.append(Issue(_format_path(loc), _message(item), line, column))
        raise SpecError(file, issues) from error


def load_spec(path: Path) -> Spec:
    """Read and validate the spec at ``path``."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise SpecError(path, [Issue("", f"cannot read file: {error.strerror or error}")]) from error
    return parse_spec(text, path)
