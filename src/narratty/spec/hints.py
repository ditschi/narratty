"""Hints for valid but redundant spec lines (``narratty validate`` prints them).

A hint never fails validation; it points at lines that can be left out or written
shorter, so specs only carry what differs from the defaults.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from narratty.spec.loader import Issue, format_path, parse_document, position, read_spec_text
from narratty.spec.model import (
    DEFAULT_VOICES,
    Enter,
    Hold,
    Key,
    Scene,
    Spec,
    TtsConfig,
    TypeCommand,
    Wait,
    WaitSpec,
)

Loc = tuple[int | str, ...]


def load_spec_with_hints(path: Path) -> tuple[Spec, list[Issue]]:
    """Read and validate the spec at ``path`` and collect its hints."""
    spec, data = parse_document(read_spec_text(path), path)
    return spec, find_hints(spec, data)


def find_hints(spec: Spec, data: Mapping[str, Any]) -> list[Issue]:
    """Hints for ``spec``, positioned in ``data`` (the YAML as written), in file order."""
    found: list[tuple[Loc, str]] = []
    _defaults(spec, data, (), found)
    raw_scenes = data.get("scenes") or []
    for index, scene in enumerate(spec.scenes):
        raw = raw_scenes[index] if index < len(raw_scenes) else {}
        if isinstance(raw, Mapping):
            _defaults(scene, raw, ("scenes", index), found)
            _actions(scene, raw.get("actions") or [], ("scenes", index, "actions"), found)
    issues = [Issue(format_path(loc), message, *position(data, loc)) for loc, message in found]
    return sorted(issues, key=lambda issue: (issue.line or 0, issue.column or 0))


def _defaults(model: BaseModel, raw: Mapping[str, Any], loc: Loc, found: list[tuple[Loc, str]]) -> None:
    """Keys written with their default value (sections recurse; lists are checked elsewhere)."""
    fields = type(model).model_fields
    for key in raw:
        name = str(key)
        if name not in fields or name == "version":
            continue
        value = getattr(model, name)
        if isinstance(value, BaseModel):
            if isinstance(raw[key], Mapping):
                _defaults(value, raw[key], (*loc, name), found)
            continue
        if isinstance(model, TtsConfig) and name == "voice":
            default = DEFAULT_VOICES.get(model.provider)
        elif fields[name].is_required():
            continue
        else:
            default = fields[name].get_default(call_default_factory=True)
        if value == default:
            found.append(((*loc, name), "same as the default; leave it out"))


def _actions(scene: Scene, raw: Sequence[Any], loc: Loc, found: list[tuple[Loc, str]]) -> None:
    actions = scene.actions
    for index, action in enumerate(actions):
        here = (*loc, index)
        following = actions[index + 1] if index + 1 < len(actions) else None
        if isinstance(action, Enter):
            found.append((here, "write `key: Enter`"))
        elif isinstance(action, TypeCommand) and _is_enter(following):
            found.append((here, "type_command followed by Enter can be written as `run: ...`"))
        elif isinstance(action, Hold) and action.hold == "auto":
            if scene.narration_start == "after_actions":
                found.append((here, "'hold: auto' has no effect with narration_start: after_actions"))
            elif following is None:
                found.append((here, "'hold: auto' has no effect at the end of a scene; leave it out"))
        elif isinstance(action, Wait) and index < len(raw):
            _wait(action, raw[index], here, found)


def _wait(action: Wait, raw: Any, loc: Loc, found: list[tuple[Loc, str]]) -> None:
    """A ``wait`` mapping that only gives the pattern, or the default timeout."""
    spec = raw.get("wait") if isinstance(raw, Mapping) else None
    if not isinstance(spec, Mapping):
        return
    if set(spec) == {"screen"}:
        found.append(((*loc, "wait"), 'write `wait: "<pattern>"`'))
    elif "timeout_ms" in spec and action.wait.timeout_ms == WaitSpec.model_fields["timeout_ms"].default:
        found.append(((*loc, "wait", "timeout_ms"), "same as the default; leave it out"))


def _is_enter(action: Any) -> bool:
    return isinstance(action, Enter) or (isinstance(action, Key) and action.key == "Enter")
