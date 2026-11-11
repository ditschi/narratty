"""The spec with its ``markdown`` entries expanded: ``narratty compile`` and sandboxed runs.

The container only gets the spec file, not the Markdown docs it points at, so a
sandboxed run hands it the expanded YAML instead.
"""

from __future__ import annotations

import hashlib
import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from narratty.spec.loader import Document, parse_document, position, read_spec_text, to_plain


@dataclass(frozen=True)
class Source:
    """Where a part of the video comes from, for ``narratty plan --sources``."""

    file: Path
    line: int | None
    scene: str | None
    what: str


def has_markdown(document: Document) -> bool:
    """True when a scene of ``document`` was expanded from Markdown."""
    return any(not isinstance(origin, int) for origin in document.origins)


def compile_document(document: Document, spec_file: Path) -> str:
    """The YAML of ``document`` with every ``markdown`` entry replaced by its scenes.

    Hand-written parts keep their comments; expanded scenes get a comment naming the
    Markdown line they came from.
    """
    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedSeq

    data = document.data
    raw_scenes = data["scenes"]
    scenes = CommentedSeq()
    for number, origin in enumerate(document.origins):
        if isinstance(origin, int):
            scenes.append(raw_scenes[origin])
            continue
        scenes.append(_flow_leaves(origin.data))
        scenes.yaml_set_comment_before_after_key(
            number, before=f"from {_relative(origin.file, spec_file)}:{origin.line}", indent=2
        )
    data["scenes"] = scenes
    data.pop("narration", None)  # only read by markdown entries
    yaml = YAML()
    yaml.width = 100
    yaml.indent(mapping=2, sequence=4, offset=2)
    out = io.StringIO()
    yaml.dump(data, out)
    return out.getvalue()


def compile_spec(spec_file: Path) -> str:
    """The expanded YAML of the spec at ``spec_file``."""
    return compile_document(parse_document(read_spec_text(spec_file), spec_file), spec_file)


def container_spec(spec_file: Path, cache: Path) -> Path | None:
    """A compiled copy of the spec to mount into a container, or None when it has no Markdown."""
    document = parse_document(read_spec_text(spec_file), spec_file)
    if not has_markdown(document):
        return None
    text = compile_document(document, spec_file)
    folder = cache / "compiled"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{hashlib.sha256(text.encode()).hexdigest()[:12]}-{spec_file.name}"
    path.write_text(text, encoding="utf-8")
    return path


def sources(spec_file: Path) -> list[Source]:
    """What each part of the video comes from, in scene order, and what was left out."""
    from narratty.spec.markdown import explain_entry
    from narratty.spec.model import MarkdownEntry

    document = parse_document(read_spec_text(spec_file), spec_file)
    data: dict[Any, Any] = document.data
    default = document.spec.narration
    found: list[Source] = []
    for index, raw in enumerate(data["scenes"]):
        if isinstance(raw, dict) and "markdown" in raw:
            entry = MarkdownEntry.model_validate(to_plain(raw))
            expansion = explain_entry(entry, spec_file.parent / entry.markdown, entry.narration or default)
            found += [Source(note.file, note.line, note.scene, note.what) for note in expansion.notes]
        else:
            line, _ = position(data, ("scenes", index))
            found.append(Source(spec_file, line, str(raw.get("id")), "YAML scene"))
    return found


def _flow_leaves(value: Any, depth: int = 0) -> Any:
    """``value`` with an action's inner mappings in flow style: ``wait: {prompt: true}``.

    ``depth`` counts from the scene (0): its actions list (1), an action (2), its options (3).
    """
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    if isinstance(value, list):
        return CommentedSeq(_flow_leaves(item, depth + 1) for item in value)
    if not isinstance(value, dict):
        return value
    mapping = CommentedMap((key, _flow_leaves(item, depth + 1)) for key, item in value.items())
    if depth >= 3 and not any(isinstance(item, (dict, list)) for item in value.values()):
        mapping.fa.set_flow_style()
    return mapping


def _relative(path: Path, spec_file: Path) -> str:
    return os.path.relpath(path.resolve(), spec_file.resolve().parent)
