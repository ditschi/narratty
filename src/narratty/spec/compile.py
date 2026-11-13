"""The spec with its ``markdown`` entries expanded: ``narratty compile`` and sandboxed runs.

The container only gets the spec file, not the Markdown docs it points at, so a
sandboxed run hands it the expanded YAML instead.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from narratty.errors import NarrattyError
from narratty.spec.loader import Document, parse_document, position, read_spec_text, to_plain
from narratty.spec.model import Run

if TYPE_CHECKING:
    from collections.abc import Iterator

# Scene id -> Markdown file:line, handed to a container that only gets the compiled spec.
SCENE_SOURCES_ENV = "NARRATTY_SCENE_SOURCES"


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
    return out.getvalue().lstrip("\n")  # a doc's spec comment keeps its line numbers with blank lines


def compile_spec(spec_file: Path) -> str:
    """The expanded YAML of the spec at ``spec_file``."""
    return compile_document(parse_document(read_spec_text(spec_file), spec_file), spec_file)


def fingerprint(spec_file: Path) -> str:
    """A hash of what the video of ``spec_file`` shows and says, Markdown entries expanded.

    Unchanged by moved lines, comments and newly added defaults; a committed video can
    store it to notice when its spec or Markdown source has changed since it was rendered.
    ``expect_output`` is left out: only ``narratty check`` reads it.
    """
    spec = parse_document(read_spec_text(spec_file), spec_file).spec
    scenes = [
        scene.model_copy(
            update={
                "actions": [
                    action.model_copy(update={"expect_output": None}) if isinstance(action, Run) else action
                    for action in scene.actions
                ]
            }
        )
        for scene in spec.scenes
    ]
    shown = spec.model_copy(update={"scenes": scenes})
    return hashlib.sha256(shown.model_dump_json(exclude_defaults=True).encode()).hexdigest()


def container_spec(spec_file: Path, cache: Path) -> Path | None:
    """A compiled copy of the spec to mount into a container, or None when it has no Markdown.

    It holds every command, including those of ``hidden`` comments, so it is readable
    only by you and the caller removes it once the container is done.
    """
    import tempfile

    document = parse_document(read_spec_text(spec_file), spec_file)
    if not has_markdown(document):
        return None
    text = compile_document(document, spec_file)
    folder = cache / "compiled"
    folder.mkdir(parents=True, exist_ok=True)
    prefix = f"{hashlib.sha256(text.encode()).hexdigest()[:12]}-"
    handle, name = tempfile.mkstemp(prefix=prefix, suffix=f"-{spec_file.name}", dir=folder)  # mode 0600
    with os.fdopen(handle, "w", encoding="utf-8") as file:
        file.write(text)
    return Path(name)


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


def markdown_warnings(document: Document, spec_file: Path) -> list[Source]:
    """Authoring warnings for the Markdown docs of ``document`` (``narratty validate``)."""
    from narratty.spec.markdown.lint import lint_entry
    from narratty.spec.model import MarkdownEntry

    found: list[Source] = []
    for raw in document.data["scenes"]:
        if isinstance(raw, dict) and "markdown" in raw:
            entry = MarkdownEntry.model_validate(to_plain(raw))
            path = spec_file.parent / entry.markdown
            notes = lint_entry(entry, path, entry.narration or document.spec.narration)
            found += [Source(Path(os.path.normpath(note.file)), note.line, None, note.what) for note in notes]
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


def scene_sources(spec_file: Path) -> dict[str, str]:
    """``file:line`` of each scene that came from Markdown, the file relative to the cwd."""
    try:
        document = parse_document(read_spec_text(spec_file), spec_file)
    except (NarrattyError, OSError):
        return {}
    found = {}
    for scene, origin in zip(document.spec.scenes, document.origins, strict=False):
        if not isinstance(origin, int):
            found[scene.id] = f"{os.path.relpath(origin.file)}:{origin.line}"
    return found


def _sources_for(spec_file: Path) -> dict[str, str]:
    handed = os.environ.get(SCENE_SOURCES_ENV)
    if handed:
        try:
            data = json.loads(handed)
        except ValueError:
            data = None
        if isinstance(data, dict):
            return {str(key): str(value) for key, value in data.items()}
    return scene_sources(spec_file)


def locate(error: NarrattyError, spec_file: Path) -> None:
    """Add the Markdown ``file:line`` of the error's scene to its message, when known."""
    if not error.scene:
        return
    source = _sources_for(spec_file).get(error.scene)
    named = f"scene {error.scene!r}"
    if named in error.message:
        if source and source not in error.message:
            error.message = error.message.replace(named, f"{named} ({source})", 1)
    else:
        error.message += f" (scene {error.scene!r}" + (f", {source})" if source else ")")
    error.args = (error.message,)


MARKDOWN_HINTS = (
    (
        "set `expect_exit: failure` (must fail) or `expect_exit: any` (not checked) on the scene or its "
        "`run` action",
        'mark the block narratty="expect-failure" (must fail), or give it an id and set '
        "`expect_exit: any` for it in the entry's `overrides` (not checked)",
    ),
    (
        "Check the pattern against the command's output, or raise wait.timeout_ms.",
        "Check the `until` pattern against the command's output, or raise `timeout` in the block's run "
        "comment.",
    ),
    ("or raise wait.timeout_ms.", "or stop it with `until` in the block's run comment."),
)
"""Phrases of hints written for YAML specs, and what they say for a Markdown doc instead."""


def markdown_hint(hint: str) -> str:
    """``hint`` in the terms of a Markdown doc."""
    for yaml, markdown in MARKDOWN_HINTS:
        hint = hint.replace(yaml, markdown)
    return hint


@contextmanager
def located(spec_file: Path) -> Iterator[None]:
    """Errors raised inside name the scene and the Markdown line they happened at.

    Their hints speak of Markdown when the spec is a doc or reads one.
    """
    try:
        yield
    except NarrattyError as error:
        locate(error, spec_file)
        if error.hint and _sources_for(spec_file):
            error.hint = markdown_hint(error.hint)
        raise
