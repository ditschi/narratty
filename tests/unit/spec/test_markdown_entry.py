"""``markdown`` entries in ``scenes``: validation and expansion by the loader.

The Markdown rules themselves are tested with the parser; here a fake expander stands in.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import jsonschema
import pytest
from ruamel.yaml import YAML

from narratty.spec import SpecError
from narratty.spec import markdown as markdown_module
from narratty.spec.hints import find_hints
from narratty.spec.loader import Issue, parse_document, parse_spec
from narratty.spec.markdown import ExpandedScene
from narratty.spec.model import HeadingOverlays, MarkdownEntry, MarkdownNarration, Run
from narratty.spec.schema import spec_schema


@pytest.fixture
def spec_file(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    return tmp_path / "demo.narratty.yaml"


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[MarkdownEntry, Path, MarkdownNarration]]:
    """Replace the expander with one that yields two scenes per entry."""
    seen: list[tuple[MarkdownEntry, Path, MarkdownNarration]] = []

    def expand(entry: MarkdownEntry, path: Path, narration: MarkdownNarration) -> list[ExpandedScene]:
        seen.append((entry, path, narration))
        prefix = entry.id_prefix or path.stem
        return [
            ExpandedScene({"id": f"{prefix}-a", "narration": "First."}, path, 3),
            ExpandedScene({"id": f"{prefix}-b", "actions": [{"run": "ls"}]}, path, 7),
        ]

    monkeypatch.setattr(markdown_module, "expand_entry", expand)
    return seen


def _issues(text: str, file: Path) -> list[str]:
    with pytest.raises(SpecError) as info:
        parse_spec(text, file)
    return [issue.render(file) for issue in info.value.issues]


def test_entry_expands_in_place(spec_file: Path, calls: list[Any]) -> None:
    text = "scenes:\n  - id: intro\n  - markdown: docs/guide.md\n  - id: outro\n"
    spec = parse_spec(text, spec_file)
    assert [scene.id for scene in spec.scenes] == ["intro", "guide-a", "guide-b", "outro"]
    assert spec.scenes[2].actions == [Run(run="ls")]
    ((entry, path, narration),) = calls
    assert path == spec_file.parent / "docs" / "guide.md"
    assert (entry.sections, narration) == (None, "all")


def test_narration_falls_back_to_the_spec(spec_file: Path, calls: list[Any]) -> None:
    text = (
        "narration: none\nscenes:\n"
        "  - markdown: docs/guide.md\n"
        "  - {markdown: docs/guide.md, id_prefix: again, narration: all}\n"
    )
    parse_spec(text, spec_file)
    assert [narration for _, _, narration in calls] == ["none", "all"]


def test_entry_keys_are_parsed(spec_file: Path, calls: list[Any]) -> None:
    text = """\
scenes:
  - markdown: docs/guide.md
    sections: [images, [compose, services]]
    heading_overlays: 3
    tabs: [macOS]
    defaults: {typing_speed_ms: 40ms, fast: true}
    overrides:
      install:
        narration: Install it with uv.
        before: [enter, {overlay: pipx works too}]
"""
    parse_spec(text, spec_file)
    ((entry, _, _),) = calls
    assert entry.sections == ["images", ["compose", "services"]]
    assert entry.heading_overlays == HeadingOverlays(levels=3)
    assert entry.defaults.typing_speed_ms == 40
    assert entry.overrides["install"].before[0].model_dump() == {"enter": True}


def test_unknown_entry_key_is_positioned(spec_file: Path, calls: list[Any]) -> None:
    text = "scenes:\n  - markdown: docs/guide.md\n    sectons: [a]\n"
    assert _issues(text, spec_file) == [
        f"{spec_file}:3:5: scenes[0].sectons: unknown key 'sectons' (did you mean 'sections'?)"
    ]
    assert calls == []


def test_missing_file_is_positioned(spec_file: Path, calls: list[Any]) -> None:
    text = "scenes:\n  - id: a\n  - markdown: docs/nope.md\n"
    (issue,) = _issues(text, spec_file)
    assert issue.startswith(f"{spec_file}:3:5: scenes[1].markdown: no such file: ")


def test_expanded_scene_problems_point_at_the_markdown(
    spec_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def expand(entry: MarkdownEntry, path: Path, narration: MarkdownNarration) -> list[ExpandedScene]:
        return [ExpandedScene({"id": "guide-a", "actions": [{"hold": "fast"}]}, path, 12)]

    monkeypatch.setattr(markdown_module, "expand_entry", expand)
    (issue,) = _issues("scenes:\n  - markdown: docs/guide.md\n", spec_file)
    md = spec_file.parent / "docs" / "guide.md"
    assert issue.startswith(f"{md}:12:1: scene 'guide-a': actions[0].hold: expected 'auto'")


def test_yaml_scene_problems_keep_their_index(spec_file: Path, calls: list[Any]) -> None:
    text = "scenes:\n  - markdown: docs/guide.md\n  - id: a\n    hiden: true\n"
    assert _issues(text, spec_file) == [
        f"{spec_file}:4:5: scenes[1].hiden: unknown key 'hiden' (did you mean 'hidden'?)"
    ]


def test_duplicate_ids_across_entries(spec_file: Path, calls: list[Any]) -> None:
    text = "scenes:\n  - markdown: docs/guide.md\n  - markdown: docs/guide.md\n"
    assert _issues(text, spec_file) == [f"{spec_file}: duplicate scene id 'guide-a'"]


def test_expander_errors_name_the_markdown_file(spec_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def expand(entry: MarkdownEntry, path: Path, narration: MarkdownNarration) -> list[ExpandedScene]:
        raise SpecError(path, [Issue("sections", "no section 'imgaes' (did you mean 'images'?)", 1)])

    monkeypatch.setattr(markdown_module, "expand_entry", expand)
    md = spec_file.parent / "docs" / "guide.md"
    assert _issues("scenes:\n  - markdown: docs/guide.md\n", spec_file) == [
        f"{md}:1:1: sections: no section 'imgaes' (did you mean 'images'?)"
    ]


def test_hints_skip_expanded_scenes(spec_file: Path, calls: list[Any]) -> None:
    text = "scenes:\n  - markdown: docs/guide.md\n  - id: a\n    hidden: false\n"
    hints = find_hints(*parse_document(text, spec_file))
    assert [hint.render(spec_file) for hint in hints] == [
        f"{spec_file}:4:5: scenes[1].hidden: same as the default; leave it out"
    ]


def test_schema_accepts_entries() -> None:
    data = YAML(typ="safe").load(
        "narration: none\nscenes:\n  - id: a\n"
        "  - markdown: docs/guide.md\n    heading_overlays: 2\n"
        "    overrides: {install: {before: [diff]}}\n"
    )
    jsonschema.validate(data, spec_schema())


def test_schema_rejects_entry_typos() -> None:
    data = YAML(typ="safe").load("scenes:\n  - markdown: docs/guide.md\n    sectons: [a]\n")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, spec_schema())
