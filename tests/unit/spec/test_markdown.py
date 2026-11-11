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
from narratty.spec.markdown import EntryError, expand_entry, explain_entry
from narratty.spec.markdown.parse import Heading, parse_blocks, parse_info, slugify
from narratty.spec.markdown.scenes import breadcrumb_text, write_file
from narratty.spec.markdown.shell import split_commands
from narratty.spec.markdown.source import Line, read_source, select_tabs
from narratty.spec.model import HeadingOverlays, MarkdownEntry

FIXTURES = Path(__file__).parent / "markdown"
ROOT = Path(__file__).parents[3]
DOCS = sorted((ROOT / "docs").rglob("*.md"))


def _expand(path: Path, **keys: object) -> list[dict[str, object]]:
    entry = MarkdownEntry.model_validate({"markdown": path.name, **keys})
    return [
        {"source": f"{scene.file.relative_to(path.parent)}:{scene.line}", **scene.data}
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
        ("features", {"heading_overlays": 3}),
        (
            "features-breadcrumb",
            {"heading_overlays": {"levels": 3, "breadcrumb": True}, "file_titles": False},
        ),
        (
            "features-overrides",
            {"overrides": {"typed": {"narration": "Run it like this.", "before": ["enter"], "fast": True}}},
        ),
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


# ── commands, comments and options ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("ls\npwd\n", ["ls", "pwd"]),
        ("# only a comment\nls  # list\n", ["ls"]),
        ("echo 'a # b' \"c # d\" e#f\n", ["echo 'a # b' \"c # d\" e#f"]),
        ("cat <<-END\n\tx\n\tEND\nls\n", ["cat <<-END\n\tx\n\tEND", "ls"]),
        ("cat <<< here\nls\n", ["cat <<< here", "ls"]),
        ("while true; do\n  break\ndone\n", ["while true; do\n  break\ndone"]),
        ("{\n  echo a\n}\n", ["{\n  echo a\n}"]),
        ("echo ${HOME} $(pwd\n)\n", ["echo ${HOME} $(pwd\n)"]),
        ("make &&\n  make test\n", ["make &&\n  make test"]),
        ("echo 'multi\nline'\n", ["echo 'multi\nline'"]),
        (
            "case $1 in\n  a) echo a ;;\n  *) echo b ;;\nesac\n",
            ["case $1 in\n  a) echo a ;;\n  *) echo b ;;\nesac"],
        ),
        ("echo done\necho fi\n", ["echo done", "echo fi"]),
    ],
)
def test_shell_blocks_split_into_commands(code: str, expected: list[str]) -> None:
    assert [command.text for command in split_commands(code)] == expected


@pytest.mark.parametrize(
    ("code", "found"),
    [
        ("git clone <url>", ["<url>"]),
        ('git commit -m "<message>"', ["<message>"]),
        ("echo '<b>'", []),
        ("sort < input.txt", []),
        ("cat <<EOF\n<html>\nEOF", []),
    ],
)
def test_placeholders(code: str, found: list[str]) -> None:
    assert [name for command in split_commands(code) for name in command.placeholders] == found


def _doc(tmp_path: Path, body: str) -> Path:
    doc = tmp_path / "doc.md"
    doc.write_text(body, encoding="utf-8")
    return doc


def _error(tmp_path: Path, body: str, **keys: object) -> tuple[str, int | None]:
    doc = _doc(tmp_path, body)
    entry = MarkdownEntry.model_validate({"markdown": doc.name, **keys})
    with pytest.raises(SpecError) as info:
        expand_entry(entry, doc, "all")
    (issue,) = info.value.issues
    assert issue.file == doc
    return issue.message, issue.line


def test_placeholder_in_a_command_to_run_is_an_error(tmp_path: Path) -> None:
    message, line = _error(tmp_path, "# Doc\n\n```bash\nls\ngit clone <repo-url>\n```\n")
    assert line == 5
    assert message.startswith("<repo-url> is a placeholder; write it as $REPO_URL")
    no_run = '# Doc\n\n```bash {narratty="no-run"}\ngit clone <repo-url>\n```\n'
    assert _expand(_doc(tmp_path, no_run))[0]["actions"][0] == {"type_command": "git clone <repo-url>"}


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("<!-- narratty: speak hi -->\n", "unknown narratty comment 'speak'"),
        ('```bash {narratty="norun"}\nls\n```\n', "unknown narratty option 'norun'"),
        ('```yaml {title="a.yaml" narratty="no-run"}\na: 1\n```\n', "'no-run' only applies to shell"),
        ("<!-- narratty: overlay {text: [ -->\n", "overlay comment: invalid YAML"),
    ],
)
def test_comment_and_option_errors(tmp_path: Path, body: str, message: str) -> None:
    assert message in _error(tmp_path, "# Doc\n\n" + body)[0]


def test_unknown_override_id(tmp_path: Path) -> None:
    doc = _doc(
        tmp_path,
        "# Doc\n\n## Setup\n\n```bash {#install}\nls\n```\n\n## Other\n\n```bash {#other}\npwd\n```\n",
    )
    with pytest.raises(EntryError) as info:
        _expand(doc, overrides={"instal": {"fast": True}})
    assert (info.value.loc, info.value.message) == (
        ("overrides", "instal"),
        "no block 'instal' in the doc (did you mean 'install'?)",
    )
    with pytest.raises(EntryError, match="no block 'other' in the selected sections"):
        _expand(doc, sections=["setup"], overrides={"other": {"fast": True}})


def test_override_on_a_file_block_changes_its_visible_scene(tmp_path: Path) -> None:
    doc = _doc(tmp_path, '# Doc\n\n```toml {#cfg title="a.toml"}\nx = 1\n```\n')
    scenes = _expand(doc, overrides={"cfg": {"narration": "The config."}})
    assert [(scene["id"], scene.get("narration")) for scene in scenes] == [
        ("doc-cfg-write", None),
        ("doc-cfg", "The config."),
    ]


@pytest.mark.parametrize(
    ("parts", "max_length", "expected"),
    [
        (["Environments", "Compose"], 50, "Environments › Compose"),
        (["Environments", "Compose files", "Services"], 30, "Environments › … › Services"),
        (["A", "B", "C", "D"], 9, "A › … › D"),
        (["Environments", "A very long section name"], 20, "Environments › A ve…"),
    ],
)
def test_breadcrumb_text(parts: list[str], max_length: int, expected: str) -> None:
    settings = HeadingOverlays(levels=4, breadcrumb=True, max_length=max(max_length, 10))
    assert breadcrumb_text(parts, settings.model_copy(update={"max_length": max_length})) == expected


def test_write_file_picks_a_free_delimiter() -> None:
    command = write_file("dir/my file.txt", "a\nNARRATTY_EOF\n")
    assert (
        command == "mkdir -p dir && cat > 'dir/my file.txt' <<'NARRATTY_EOF_'\na\nNARRATTY_EOF\nNARRATTY_EOF_"
    )


def test_notes_explain_every_part(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "# Doc\n\nSpoken.\n\n| a |\n|---|\n| b |\n\n```yaml\na: 1\n```\n")
    entry = MarkdownEntry(markdown=doc.name)
    notes = [(note.line, note.scene, note.what) for note in explain_entry(entry, doc, "all").notes]
    assert notes == [
        (3, "doc-1", "paragraph: spoken"),
        (5, None, "table: not part of the video"),
        (9, None, "yaml block: left out (no title)"),
    ]


# ── images ────────────────────────────────────────────────────────────────────


def _image_doc(tmp_path: Path, body: str) -> Path:
    (tmp_path / "pic.png").write_bytes((FIXTURES / "image.png").read_bytes())
    return _doc(tmp_path, "# Doc\n\n" + body)


def test_an_image_shows_with_the_text_around_it(tmp_path: Path) -> None:
    doc = _image_doc(tmp_path, "Before.\n\n![A picture](pic.png)\n\nAfter.\n\n## Next\n\nNext text.\n")
    first, second = _expand(doc)
    assert first["narration"] == "Before. After."
    (browser,) = first["actions"]
    assert browser["browser"]["address"] == "pic.png"
    assert browser["browser"]["url"].startswith("data:text/html;base64,")
    assert "actions" not in second


def test_an_image_never_covers_commands(tmp_path: Path) -> None:
    doc = _image_doc(tmp_path, "Look.\n\n![A picture](pic.png)\n\n```bash\nls\n```\n")
    image, command = _expand(doc)
    assert [next(iter(action)) for action in image["actions"]] == ["browser"]
    assert command["actions"][0] == {"run": "ls"}
    assert "narration" not in command


def test_an_image_without_text_is_held(tmp_path: Path) -> None:
    (scene,) = _expand(_image_doc(tmp_path, "![A picture](pic.png)\n"))
    assert scene["actions"][-1] == {"hold": 3000}


@pytest.mark.parametrize(
    ("body", "keys", "what"),
    [
        ("![x](pic.png)\n", {"images": False}, "image: left out (images: false)"),
        ("![x](https://example.com/a.png)\n", {}, "image: left out (not a local file)"),
        ("![x](notes.pdf)\n", {}, "image: left out (.pdf files are not shown)"),
        ("<!-- narratty: skip -->\n![x](pic.png)\n", {}, "image: left out by a skip comment"),
    ],
)
def test_images_left_out(tmp_path: Path, body: str, keys: dict[str, object], what: str) -> None:
    doc = _image_doc(tmp_path, body)
    entry = MarkdownEntry.model_validate({"markdown": doc.name, **keys})
    expansion = explain_entry(entry, doc, "all")
    assert expansion.scenes == []
    assert what in [note.what for note in expansion.notes]


def test_missing_image_is_an_error(tmp_path: Path) -> None:
    message, line = _error(tmp_path, "# Doc\n\n![x](missing.png)\n")
    assert (message, line) == ("image not found: missing.png", 3)


# ── browser comments ──────────────────────────────────────────────────────────

COMPOSE = (
    "Intro text.\n\n"
    "<!-- narratty: browser {scroll: auto, duration_ms: 6s} -->\n"
    "The [Compose file reference](https://docs.docker.com/compose/) lists every key.\n\n"
    "More about it.\n\n"
    "```bash\nls\n```\n"
)


def test_browser_comment_opens_the_first_link(tmp_path: Path) -> None:
    intro, page, command = _expand(_doc(tmp_path, "# Doc\n\n" + COMPOSE))
    assert intro["narration"] == "Intro text."
    assert page["narration"] == "The Compose file reference lists every key. More about it."
    assert page["actions"] == [
        {"browser": {"url": "https://docs.docker.com/compose/", "scroll": "auto", "duration_ms": "6s"}}
    ]
    assert command["actions"][0] == {"run": "ls"}, "the page never covers commands"


@pytest.mark.parametrize(
    ("options", "url"),
    [
        ("{link: 2}", "https://b.example/"),
        ('{link: "First"}', "https://a.example/"),
        ("https://c.example/", "https://c.example/"),
    ],
)
def test_browser_comment_picks_a_link(tmp_path: Path, options: str, url: str) -> None:
    body = f"# Doc\n\n<!-- narratty: browser {options} -->\nSee [First](https://a.example/) and [Second](https://b.example/).\n"
    (scene,) = _expand(_doc(tmp_path, body))
    assert scene["actions"][0]["browser"]["url"] == url


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("<!-- narratty: browser -->\nNo link here.\n", "the next paragraph has no link"),
        ("<!-- narratty: browser -->\n## Heading\n", "the next paragraph has no link"),
        ("<!-- narratty: browser {link: 3} -->\n[a](https://a.example/)\n", "the paragraph has 1 link(s)"),
        (
            "<!-- narratty: browser {link: Fist} -->\n[First](https://a.example/)\n",
            "no link 'Fist' (did you mean 'First'?)",
        ),
        ("<!-- narratty: browser -->\nSee [spec](spec.md).\n", "set site_url in mkdocs.yml"),
    ],
)
def test_browser_comment_errors(tmp_path: Path, body: str, message: str) -> None:
    (tmp_path / ".git").mkdir()
    text, line = _error(tmp_path, "# Doc\n\n" + body)
    assert message in text
    assert line == 3


def test_relative_links_open_the_published_page(tmp_path: Path) -> None:
    (tmp_path / "mkdocs.yml").write_text("site_url: https://example.org/docs/\n", encoding="utf-8")
    guide = tmp_path / "docs" / "guide"
    guide.mkdir(parents=True)
    doc = guide / "intro.md"
    doc.write_text(
        "# Intro\n\n<!-- narratty: browser -->\nSee [overlays](../spec.md#overlays).\n\n"
        "<!-- narratty: browser -->\nOr [home](../index.md) and [here](#intro).\n",
        encoding="utf-8",
    )
    first, second = _expand(doc)
    assert first["actions"][0]["browser"]["url"] == "https://example.org/docs/spec/#overlays"
    assert second["actions"][0]["browser"]["url"] == "https://example.org/docs/"
