"""A Markdown doc built on its own: the spec its ``spec`` comment implies."""

from __future__ import annotations

from pathlib import Path

import pytest

from narratty.spec import SpecError
from narratty.spec.compile import compile_spec
from narratty.spec.loader import is_markdown, load_spec, parse_document, read_spec_text
from narratty.spec.model import ShowOverlay

DOC = """\
# Hello

<!-- narratty: spec
tts: {voice: am_michael}
heading_overlays: 2
sections: [usage]
-->

## Usage

Say hello.

```console
$ echo hello
hello
```
"""


def _doc(tmp_path: Path, text: str = DOC) -> Path:
    path = tmp_path / "hello.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_markdown_suffixes() -> None:
    assert is_markdown(Path("a/guide.md")) and is_markdown(Path("README.MARKDOWN"))
    assert not is_markdown(Path("demo.narratty.yaml"))


def test_a_doc_without_spec_comment_is_one_markdown_entry(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "Say hello.\n\n```console\n$ echo hello\n```\n")
    assert read_spec_text(doc) == ""
    spec = load_spec(doc)
    assert [scene.id for scene in spec.scenes] == ["hello-1"]
    assert spec.workspace.source == ".", "outside a git repository the doc's folder"


def test_spec_comment_sets_spec_and_entry_keys(tmp_path: Path) -> None:
    document = parse_document(read_spec_text(_doc(tmp_path)), tmp_path / "hello.md")
    assert document.spec.tts.voice == "am_michael"
    assert document.data["scenes"][0] == {
        "markdown": "hello.md",
        "heading_overlays": 2,
        "sections": ["usage"],
    }
    scene = document.spec.scenes[0]
    assert scene.id == "hello-usage-1"
    assert scene.actions[0].overlay.style == "heading-2"  # type: ignore[union-attr]


def test_problems_are_reported_at_the_doc_line(tmp_path: Path) -> None:
    doc = _doc(tmp_path, DOC.replace("heading_overlays", "heading_overlay"))
    with pytest.raises(SpecError) as caught:
        load_spec(doc)
    rendered = [issue.render(doc) for issue in caught.value.issues]
    assert rendered == [
        f"{doc}:5:1: heading_overlay: unknown key 'heading_overlay' (did you mean 'heading_overlays'?)"
    ]
    doc = _doc(tmp_path, DOC.replace("[usage]", "[nope]"))
    with pytest.raises(SpecError) as caught:
        load_spec(doc)
    assert caught.value.issues[0].line == 6
    assert "no section 'nope'" in caught.value.issues[0].message


def test_spec_comment_cannot_hold_scenes(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "<!-- narratty: spec\nscenes: []\n-->\n\nText.\n")
    with pytest.raises(SpecError, match="cannot hold scenes") as caught:
        load_spec(doc)
    assert caught.value.issues[0].line == 2


def test_one_spec_comment_per_doc(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "<!-- narratty: spec {} -->\n\nText.\n\n<!-- narratty: spec {} -->\n")
    with pytest.raises(SpecError, match="one spec comment; the first is on line 1"):
        load_spec(doc)


def test_spec_comment_must_be_a_mapping(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "Text.\n\n<!-- narratty: spec\n- a\n-->\n")
    with pytest.raises(SpecError, match="expected a YAML mapping") as caught:
        load_spec(doc)
    assert caught.value.issues[0].line == 4


def test_commands_run_at_the_repository_root(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "docs").mkdir()
    doc = tmp_path / "docs" / "hello.md"
    doc.write_text("Text.\n", encoding="utf-8")
    assert load_spec(doc).workspace.source == ".."
    doc.write_text("<!-- narratty: spec\nworkspace: {source: .}\n-->\n\nText.\n", encoding="utf-8")
    assert load_spec(doc).workspace.source == "."


def test_a_spec_pointing_at_the_doc_ignores_its_spec_comment(tmp_path: Path) -> None:
    _doc(tmp_path)
    spec = tmp_path / "hello.narratty.yaml"
    spec.write_text("scenes:\n  - markdown: hello.md\n", encoding="utf-8")
    loaded = load_spec(spec)
    assert loaded.tts.voice == "af_heart"
    assert [scene.id for scene in loaded.scenes] == ["hello-usage-1"]
    assert not any(isinstance(action, ShowOverlay) for action in loaded.scenes[0].actions)


def test_compile_writes_the_implied_spec(tmp_path: Path) -> None:
    text = compile_spec(_doc(tmp_path))
    assert text.startswith("tts: {voice: am_michael}\nscenes:\n  # from hello.md:13\n  - id: hello-usage-1\n")
