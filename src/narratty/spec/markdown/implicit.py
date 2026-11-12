"""A Markdown doc built on its own (``narratty build guide.md``): the spec it implies.

That spec has one scene entry, ``markdown: guide.md``. A ``<!-- narratty: spec ... -->``
comment in the doc adds top-level keys and the entry's own keys (``sections``,
``heading_overlays``, ...). Its YAML keeps its line numbers in the doc, so problems are
reported where they were written.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from narratty.spec.loader import Issue, SpecError, position
from narratty.spec.model import MarkdownEntry, Spec

SPEC_COMMENT = re.compile(r"^\s*narratty:\s*spec(?![\w-])")
ENTRY_KEYS = tuple(
    key for key in MarkdownEntry.model_fields if key not in Spec.model_fields and key != "markdown"
)


def spec_comment_text(path: Path) -> str:
    """The YAML of the doc's ``spec`` comment, at its line numbers in the doc ("" without one)."""
    from narratty.spec.markdown.parse import Comment, parse_blocks
    from narratty.spec.markdown.source import fail, read_source

    comments = [
        block
        for block in parse_blocks(read_source(path))
        if isinstance(block, Comment) and block.file == path and SPEC_COMMENT.match(block.text)
    ]
    if not comments:
        return ""
    if len(comments) > 1:
        raise fail(
            path, comments[1].line, f"a doc has one spec comment; the first is on line {comments[0].line}"
        )
    comment = comments[0]
    head = SPEC_COMMENT.match(comment.text)
    assert head is not None
    line = comment.line + comment.text[: head.end()].count("\n")
    return "\n" * (line - 1) + comment.text[head.end() :]


def implied_spec(data: CommentedMap, doc: Path) -> CommentedMap:
    """``data`` (the spec comment's keys) with the doc as its only scene entry.

    Keys of a markdown entry move into the entry. ``workspace.source`` defaults to the
    root of the doc's git repository, where its commands usually run.
    """
    if "scenes" in data:
        message = (
            "the spec comment cannot hold scenes; for more scenes, write a YAML spec with a markdown entry"
        )
        raise SpecError(doc, [Issue("scenes", message, *position(data, ("scenes",)), doc)])
    entry = CommentedMap()
    entry["markdown"] = doc.name
    first: list[int] | None = None
    for key in [key for key in data if key in ENTRY_KEYS]:
        at = data.lc.data.get(key) if data.lc.data else None
        entry[key] = data.pop(key)
        if at is not None:
            entry.lc.add_kv_line_col(key, at)
            first = first or at
    _default_workspace(data, doc)
    scenes = CommentedSeq([entry])
    if first is not None:
        scenes.lc.add_idx_line_col(0, first)
        data.lc.add_kv_line_col("scenes", first)
    data["scenes"] = scenes
    return data


def _default_workspace(data: CommentedMap, doc: Path) -> None:
    workspace = data.get("workspace", CommentedMap())
    if not isinstance(workspace, dict) or "source" in workspace:
        return
    root = next((folder for folder in doc.resolve().parents if (folder / ".git").exists()), None)
    if root is None or root == doc.resolve().parent:
        return
    workspace["source"] = os.path.relpath(root, doc.resolve().parent)
    data["workspace"] = workspace
