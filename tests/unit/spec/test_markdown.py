"""Markdown docs to scenes: golden fixtures, section selection, tabs and snippets.

Regenerate the golden files with ``NARRATTY_UPDATE_GOLDEN=1 pytest tests/unit/spec/test_markdown.py``
and review the diff.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from narratty.spec import SpecError
from narratty.spec.loader import parse_document
from narratty.spec.markdown import EntryError, expand_entry
from narratty.spec.markdown.parse import Heading, parse_blocks, parse_info, slugify
from narratty.spec.markdown.source import Line, read_source, select_tabs
from narratty.spec.model import MarkdownEntry

FIXTURES = Path(__file__).parent / "markdown"
ROOT = Path(__file__).parents[3]
DOCS = sorted((ROOT / "docs").rglob("*.md"))


def _expand(path: Path, **keys: object) -> list[dict[str, object]]:
    entry = MarkdownEntry.model_validate({"markdown": path.name, **keys})
    return [
        {"source": f"{scene.file.relative_to(FIXTURES)}:{scene.line}", **scene.data}
        for scene in expand_entry(entry, path, entry.narration or "all")
    ]


def _dump(data: object) -> str:
    yaml = YAML()
    yaml.width = 100
    out = io.StringIO()
    yaml.dump(data, out)
    return out.getvalue()


@pytest.mark.parametrize(
    ("name", "keys"),
    [
        ("constructs", {}),
        ("tabs", {}),
        ("tabs-macos", {"tabs": ["Windows", "macOS"]}),
        ("constructs-silent", {"narration": "none", "defaults": {"typing_speed_ms": 20}}),
    ],
)
def test_golden(name: str, keys: dict[str, object]) -> None:
    source = FIXTURES / f"{name.split('-')[0]}.md"
    golden = FIXTURES / f"{name}.yaml"
    actual = _dump(_expand(source, **keys))
    if os.environ.get("NARRATTY_UPDATE_GOLDEN"):
        golden.write_text(actual, encoding="utf-8")
    assert actual == golden.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", DOCS, ids=lambda path: str(path.relative_to(ROOT / "docs")))
def test_every_doc_page_expands(path: Path) -> None:
    """This repo's docs are the corpus: each page becomes a valid spec."""
    rel = path.relative_to(ROOT)
    document = parse_document(f"scenes:\n  - markdown: {rel}\n", ROOT / "corpus.narratty.yaml")
    assert document.spec.scenes


# ── sections ──────────────────────────────────────────────────────────────────


def test_sections_in_the_entrys_order() -> None:
    scenes = _expand(FIXTURES / "constructs.md", sections=["callouts", "lists"])
    assert [scene["id"] for scene in scenes] == [
        "constructs-callouts-1",
        "constructs-lists-1",
        "constructs-lists-2",
    ]


def test_section_by_title_and_nested_headings() -> None:
    scenes = _expand(FIXTURES / "tabs.md", sections=["Tabs"])
    assert [scene["id"] for scene in scenes][-1] == "tabs-snippets-2"  # the H1 includes "Snippets"


def test_missing_section_suggests_a_slug() -> None:
    with pytest.raises(EntryError) as info:
        _expand(FIXTURES / "constructs.md", sections=["lists", "calouts"])
    assert info.value.loc == ("sections", 1)
    assert info.value.message == "no section 'calouts' in the doc (did you mean 'callouts'?)"


def test_list_path_reaches_into_a_section() -> None:
    scenes = _expand(FIXTURES / "constructs.md", sections=[["constructs", "callouts_1"]])
    assert [scene["id"] for scene in scenes] == ["constructs-callouts_1-1"]
    with pytest.raises(EntryError, match="no section 'lists'"):
        _expand(FIXTURES / "constructs.md", sections=[["callouts", "lists"]])


def test_entry_errors_are_positioned_in_the_yaml(tmp_path: Path) -> None:
    (tmp_path / "doc.md").write_text("# A\n\n## B\n", encoding="utf-8")
    file = tmp_path / "s.narratty.yaml"
    with pytest.raises(SpecError) as info:
        parse_document("scenes:\n  - markdown: doc.md\n    sections: [b, c]\n", file)
    assert [issue.render(file) for issue in info.value.issues] == [
        f"{file}:3:19: scenes[0].sections[1]: no section 'c' in the doc"
    ]


def test_title_matching_several_headings_needs_a_path(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("# Doc\n\n## A\n\n### Setup\n\n## B\n\n### Setup\n", encoding="utf-8")
    with pytest.raises(EntryError, match=r"'Setup' names 2 headings \(lines 5, 9\)"):
        _expand(doc, sections=["Setup"])
    assert _expand(doc, sections=[["b", "setup"]]) == []


# ── parsing ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "title",
    ["Spec reference", "`narratty env` up", "Äpfel & Birnen", "A — B", "Run (native)", "x_y.z"],
)
def test_slugs_match_the_mkdocs_toc(title: str) -> None:
    slugs = pytest.importorskip("pymdownx.slugs")
    expected = slugs.slugify(case="lower")(title.replace("`", ""), "-")
    assert slugify(title.replace("`", "")) == expected


def test_heading_attr_list_id() -> None:
    lines = [Line(text, Path("d.md"), n) for n, text in enumerate(["## Title {#custom .x}"], 1)]
    (heading,) = parse_blocks(lines)
    assert isinstance(heading, Heading)
    assert (heading.title, heading.slug) == ("Title", "custom")


@pytest.mark.parametrize(
    ("info", "expected"),
    [
        ("console", ("console", {})),
        (
            'console {#install narratty="no-run hidden" title="Install"}',
            ("console", {"#": "install", "narratty": "no-run hidden", "title": "Install"}),
        ),
        ('yaml title="demo.narratty.yaml"', ("yaml", {"title": "demo.narratty.yaml"})),
        ("Bash {.numberLines}", ("bash", {})),
    ],
)
def test_fence_info(info: str, expected: tuple[str, dict[str, str]]) -> None:
    assert parse_info(info) == expected


# ── tabs and snippets ─────────────────────────────────────────────────────────


def _lines(text: str) -> list[Line]:
    return [Line(line, Path("d.md"), n) for n, line in enumerate(text.splitlines(), 1)]


def test_tabs_keep_line_numbers() -> None:
    text = '=== "A"\n\n    a\n\n=== "B"\n\n    b\nafter\n'
    kept = select_tabs(_lines(text), ["B"])
    assert [(line.number, line.text) for line in kept if line.text] == [(7, "b"), (8, "after")]


def test_tabs_inside_fences_are_text() -> None:
    text = '```\n=== "A"\n    a\n```\n'
    assert [line.text for line in select_tabs(_lines(text), [])] == text.splitlines()


def test_nested_tabs() -> None:
    text = '=== "A"\n\n    === "A1"\n\n        a1\n\n    === "A2"\n\n        a2\n'
    kept = select_tabs(_lines(text), ["A2"])
    assert [line.text for line in kept if line.text] == ["a2"]


def test_snippet_lines_remember_their_file() -> None:
    lines = read_source(FIXTURES / "tabs.md")
    echo = next(line for line in lines if line.text == "echo one")
    assert (echo.file.name, echo.number) == ("setup.sh", 2)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('--8<-- "missing.md"', "snippet not found: missing.md"),
        ("--8<--", "block snippets"),
        ('--8<-- "https://example.com/a.md"', "URL snippets are not supported"),
        ('--8<-- "self.md"', "snippet includes itself"),
    ],
)
def test_snippet_errors(tmp_path: Path, text: str, message: str) -> None:
    (tmp_path / ".git").mkdir()
    doc = tmp_path / "self.md"
    doc.write_text(f"# Doc\n\n{text}\n", encoding="utf-8")
    with pytest.raises(SpecError) as info:
        read_source(doc)
    (issue,) = info.value.issues
    assert message in issue.message
    assert (issue.file, issue.line) == (doc, 3)
