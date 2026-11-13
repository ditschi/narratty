"""Markdown docs to scenes: golden fixtures, section selection, tabs and snippets.

Regenerate the golden files with ``NARRATTY_UPDATE_GOLDEN=1 pytest tests/unit/spec/test_markdown.py``
and review the diff.
"""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

from narratty.render import browser
from narratty.render.overlays import planned_times
from narratty.render.script import build_script
from narratty.spec import SpecError
from narratty.spec.loader import parse_document
from narratty.spec.markdown import EntryError, expand_entry, explain_entry
from narratty.spec.markdown.parse import Heading, parse_blocks, parse_info, slugify
from narratty.spec.markdown.scenes import breadcrumb_text, write_file
from narratty.spec.markdown.shell import split_commands
from narratty.spec.markdown.source import Line, read_source, select_tabs
from narratty.spec.model import HeadingOverlays, MarkdownEntry, Spec
from narratty.timeline import build_timeline

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


def test_console_output_becomes_expect_output(tmp_path: Path) -> None:
    body = (
        "# Doc\n\n```console\n$ for i in 1 2; do\n>   echo $i\n> done\n1\n> 2\n\n"
        "$ true\n$ echo  hi  \nhi  \n```\n"
    )
    actions = _expand(_doc(tmp_path, body))[0]["actions"]
    runs = [action for action in actions if "run" in action]
    assert runs == [
        {"run": "for i in 1 2; do\n  echo $i\ndone", "expect_output": "1\n> 2"},
        {"run": "true"},
        {"run": "echo  hi", "expect_output": "hi"},
    ]


@pytest.mark.parametrize(
    ("info", "keys"),
    [('console {narratty="any-output"}', {}), ("console", {"check_output": False})],
)
def test_output_comparison_can_be_turned_off(tmp_path: Path, info: str, keys: dict[str, object]) -> None:
    doc = _doc(tmp_path, f"# Doc\n\n```{info}\n$ date\nThu Jan  1\n```\n")
    assert _expand(doc, **keys)[0]["actions"][0] == {"run": "date"}


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
    assert _expand(_doc(tmp_path, no_run))[0]["actions"][0] == {"run": ":", "show": "git clone <repo-url>"}


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
        (9, None, 'yaml block: left out (no title; add a title or narratty="show")'),
    ]


# ── images ────────────────────────────────────────────────────────────────────


def _image_doc(tmp_path: Path, body: str) -> Path:
    (tmp_path / "pic.png").write_bytes((FIXTURES / "image.png").read_bytes())
    return _doc(tmp_path, "# Doc\n\n" + body)


def test_an_image_shows_with_the_text_around_it(tmp_path: Path) -> None:
    doc = _image_doc(tmp_path, "Before.\n\n![A picture](pic.png)\n\nAfter.\n\n## Next\n\nNext text.\n")
    first, second = _expand(doc)
    assert first["narration"] == "Before. After."
    (action,) = first["actions"]
    assert action["slide"]["image"].startswith("data:image/png;base64,")
    assert "actions" not in second


def test_an_image_never_covers_commands(tmp_path: Path) -> None:
    doc = _image_doc(tmp_path, "Look.\n\n![A picture](pic.png)\n\n```bash\nls\n```\n")
    image, command = _expand(doc)
    assert [next(iter(action)) for action in image["actions"]] == ["slide"]
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


def test_fingerprint_follows_what_the_video_shows(tmp_path: Path) -> None:
    from narratty.spec.compile import fingerprint

    doc = _doc(tmp_path, "# Doc\n\nSay this.\n\n```bash\nls\n```\n")
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text("scenes:\n  - markdown: doc.md\n", encoding="utf-8")
    first = fingerprint(spec)
    doc.write_text(
        "# Doc\n\n\n\nSay this.\n<!-- a comment -->\n\n```bash\nls  # typed? no\n```\n", encoding="utf-8"
    )
    assert fingerprint(spec) == first, "moved lines, comments and dropped shell comments change nothing"
    doc.write_text("# Doc\n\nSay this.\n\n```console\n$ ls\nREADME.md\n```\n", encoding="utf-8")
    assert fingerprint(spec) == first, "the output a console block shows is not typed"
    doc.write_text("# Doc\n\nSay that.\n\n```bash\nls\n```\n", encoding="utf-8")
    assert fingerprint(spec) != first


def _slides(scene: dict[str, object]) -> list[dict[str, Any]]:
    actions = scene["actions"]
    assert isinstance(actions, list)
    return [action["slide"] for action in actions if "slide" in action]


# ── pauses ──────────────────────────────────────────────────────────────────────────────


def test_pause_ends_the_scene_and_holds(tmp_path: Path) -> None:
    doc = _doc(
        tmp_path,
        "# Doc\n\nFirst.\n\n<!-- narratty: pause 800ms -->\n\nSecond.\n\n"
        "<!-- narratty: pause -->\nThird.\n\n```bash\nls\n```\n",
    )
    scenes = _expand(doc)
    assert [(s["id"], s.get("narration"), s.get("actions")) for s in scenes] == [
        ("doc-1", "First.", None),
        ("doc-2", None, [{"hold": 800}]),
        ("doc-3", "Second.", None),
        ("doc-4", "Third.", [{"run": "ls"}, {"wait": {"prompt": True}}]),
    ]
    notes = [note.what for note in explain_entry(MarkdownEntry(markdown=doc.name), doc, "all").notes]
    assert "pause comment: 800 ms of silence" in notes
    assert "pause comment: the scene ends here" in notes


def test_pause_needs_a_duration(tmp_path: Path) -> None:
    message, line = _error(tmp_path, "# Doc\n\n<!-- narratty: pause soon -->\n")
    assert (message, line) == ("pause comment: expected a duration such as 800ms or 1.5s, got 'soon'", 3)


# ── tables ──────────────────────────────────────────────────────────────────────────────

SAFETY = (
    "| Hazard | Severity | Mitigation |\n"
    "|---|---|---|\n"
    "| Pinch point | high | Keep the guard closed |\n"
    "| Hot surface | | Wear `gloves` <b>always</b> |\n"
)


def test_table_rows_are_spoken_one_by_one(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "# Doc\n\nThe risks.\n\n<!-- narratty: table -->\n" + SAFETY + "\nAfter.\n")
    intro, first, second, after = _expand(doc)
    assert intro["narration"] == "The risks."
    assert first["narration"] == "Hazard: Pinch point. Severity: high. Mitigation: Keep the guard closed."
    assert second["narration"] == "Hazard: Hot surface. Mitigation: Wear gloves always."
    assert (first["source"], second["source"]) == ("doc.md:8", "doc.md:9")
    (slide,) = _slides(second)
    assert slide["highlight"] == 2
    assert slide["table"]["header"] == ["Hazard", "Severity", "Mitigation"]
    assert slide["table"]["rows"][1] == ["Hot surface", "", "Wear `gloves` <b>always</b>"]
    assert _slides(first)[0]["table"] is slide["table"], "one table, shared by the row slides"
    assert after["narration"] == "After."
    assert "actions" not in after, "the table is gone after its rows"


def test_table_highlights_follow_each_row_narration(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "# Doc\n\n<!-- narratty: table -->\n" + SAFETY)
    first, second = _expand(doc)
    scenes = [{key: value for key, value in scene.items() if key != "source"} for scene in (first, second)]
    spec = Spec.model_validate({"timing": {"narration_buffer_ms": 250}, "end_card": False, "scenes": scenes})
    audio_ms = {str(first["id"]): 1800, str(second["id"]): 2400}
    timeline = build_timeline(spec, audio_ms)
    times = planned_times(build_script(spec, timeline))

    views = browser.schedule(spec, times)
    assert [view.slide.highlight for view in views if view.slide is not None] == [1, 2]
    for scene in spec.scenes:
        view = next(view for view in views if view.scene_id == scene.id)
        timing = timeline.scene(scene.id)
        assert view.start_ms == timing.start_ms
        assert view.end_ms == timing.start_ms + audio_ms[scene.id] + spec.timing.narration_buffer_ms


def test_table_template_pause_and_look(tmp_path: Path) -> None:
    comment = (
        '<!-- narratty: table {say: "{hazard}: {Mitigation}", pause: 500ms, title: Risks, rows: 1} -->\n'
    )
    first, second = _expand(_doc(tmp_path, "# Doc\n\n" + comment + SAFETY))
    assert first["narration"] == "Pinch point: Keep the guard closed"
    assert [next(iter(action)) for action in first["actions"]] == ["slide", "hold"]
    assert first["actions"][1] == {"hold": 500}
    assert first["narration_start"] == "after_actions"
    assert {key: _slides(second)[0][key] for key in ("title", "rows", "highlight")} == {
        "title": "Risks",
        "rows": 1,
        "highlight": 2,
    }


def test_table_say_list_pairs_custom_voiceover_with_row_highlights(tmp_path: Path) -> None:
    comment = "<!-- narratty: table {say: ['We guard against pinching.', 'Avoid hot surfaces.']} -->\n"
    first, second = _expand(_doc(tmp_path, "# Doc\n\n" + comment + SAFETY))
    assert first["narration"] == "We guard against pinching."
    assert second["narration"] == "Avoid hot surfaces."
    assert _slides(first)[0]["highlight"] == 1
    assert _slides(second)[0]["highlight"] == 2


def test_tables_without_a_comment_stay_out(tmp_path: Path) -> None:
    assert _expand(_doc(tmp_path, "# Doc\n\n" + SAFETY)) == []


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("<!-- narratty: table -->\nNo table.\n", "table comment: the next block is not a table"),
        ("<!-- narratty: table -->\n", "table comment: the next block is not a table"),
        (
            "<!-- narratty: table {say: '{Hazzard}'} -->\n" + SAFETY,
            "no column 'Hazzard' (did you mean 'Hazard'?)",
        ),
        (
            "<!-- narratty: table {say: ['First row only']} -->\n" + SAFETY,
            "table comment: say has 1 phrase(s) for 2 row(s)",
        ),
        ("<!-- narratty: table {speak: x} -->\n" + SAFETY, "table comment: unknown key 'speak'"),
        ("<!-- narratty: table {pause: soon} -->\n" + SAFETY, "table comment: pause: expected a duration"),
        ("<!-- narratty: table -->\n| a | b |\n|---|---|\n", "table comment: the table has no rows"),
    ],
)
def test_table_comment_errors(tmp_path: Path, body: str, message: str) -> None:
    text, line = _error(tmp_path, "# Doc\n\n" + body)
    assert message in text
    assert line == 3


def test_inline_code_reaches_the_lexicon(tmp_path: Path) -> None:
    from narratty.tts.lexicon import Entry, Lexicon

    (scene,) = _expand(_doc(tmp_path, "# Doc\n\nInstall `uv` and check the `SHA256` sum.\n"))
    lexicon = Lexicon([Entry("uv", "you vee", "spec"), Entry("SHA256", "shah two fifty six", "spec")])
    assert lexicon.apply(str(scene["narration"])) == "Install you vee and check the shah two fifty six sum."


# ── diagrams and HTML pages ───────────────────────────────────────────────────────────

MERMAID = "```mermaid\nflowchart LR\n  a[A & B] --> b\n```\n"


def test_mermaid_block_shows_like_an_image(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "# Doc\n\nBefore.\n\n" + MERMAID + "\nAfter.\n\n```bash\nls\n```\n")
    diagram, command = _expand(doc)
    assert diagram["narration"] == "Before. After."
    assert _slides(diagram) == [{"mermaid": "flowchart LR\n  a[A & B] --> b\n"}]
    assert command["actions"][0] == {"run": "ls"}


def test_mermaid_blocks_follow_images_false(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "# Doc\n\n" + MERMAID)
    expansion = explain_entry(MarkdownEntry(markdown=doc.name, images=False), doc, "all")
    assert expansion.scenes == []
    assert "mermaid block: left out (images: false)" in [note.what for note in expansion.notes]


def test_mermaid_block_takes_no_options(tmp_path: Path) -> None:
    message, _ = _error(tmp_path, '# Doc\n\n```mermaid {narratty="hidden"}\ngraph TD\n```\n')
    assert message == "'hidden' only applies to shell and console blocks"


# ── slide comments ──────────────────────────────────────────────────────────────────────


def test_slide_comment_sets_the_look(tmp_path: Path) -> None:
    body = "# Doc\n\n<!-- narratty: slide {title: Flow, theme: light} -->\n" + MERMAID + "\nThe flow.\n"
    (scene,) = _expand(_doc(tmp_path, body))
    assert _slides(scene) == [
        {"title": "Flow", "theme": "light", "mermaid": "flowchart LR\n  a[A & B] --> b\n"}
    ]


def test_slide_comment_can_focus_a_mermaid_node(tmp_path: Path) -> None:
    body = "# Doc\n\n<!-- narratty: slide {focus: api} -->\n" + MERMAID
    (scene,) = _expand(_doc(tmp_path, body))
    assert _slides(scene) == [{"focus": "api", "mermaid": "flowchart LR\n  a[A & B] --> b\n"}]


def test_markdown_mermaid_walkthrough_reuses_one_diagram_source(tmp_path: Path) -> None:
    body = (
        "# Doc\n\n<!-- narratty: slide {focus: a} -->\n"
        + MERMAID
        + "The request arrives.\n\n<!-- narratty: focus b -->\n\nThe database stores it.\n"
    )
    first, second = _expand(_doc(tmp_path, body))
    assert body.count("```mermaid") == 1
    assert [scene["narration"] for scene in (first, second)] == [
        "The request arrives.",
        "The database stores it.",
    ]
    assert [_slides(scene)[0]["focus"] for scene in (first, second)] == ["a", "b"]


@pytest.mark.parametrize(
    "between",
    [
        "## Next\n\nA new section.\n\n",
        "```bash\nls\n```\n\n",
        "![x](pic.png)\n\n",
        "<!-- narratty: slide -->\n| A |\n|---|\n| 1 |\n\n",
        "<!-- narratty: browser https://example.com -->\nThe site.\n\n",
    ],
    ids=["heading", "command", "image", "table", "browser"],
)
def test_focus_comment_does_not_bring_back_an_old_diagram(tmp_path: Path, between: str) -> None:
    (tmp_path / "pic.png").write_bytes(b"png")
    body = "# Doc\n\n" + MERMAID + "The flow.\n\n" + between + "More.\n\n<!-- narratty: focus b -->\n"
    message, _ = _error(tmp_path, body)
    assert message.startswith("focus comment: no Mermaid diagram on screen")


def test_focus_comment_still_follows_a_hidden_command(tmp_path: Path) -> None:
    body = "# Doc\n\n" + MERMAID + "The flow.\n\n<!-- narratty: hidden ls -->\n\n<!-- narratty: focus b -->\n"
    scenes = _expand(_doc(tmp_path, body))
    assert _slides(scenes[-1]) == [{"mermaid": "flowchart LR\n  a[A & B] --> b\n", "focus": "b"}]


@pytest.mark.parametrize(
    ("keys", "note"),
    [
        ({"narration": "none"}, "focus comment: left out (narration: none)"),
        ({"images": False}, "focus comment: left out (images: false)"),
    ],
)
def test_focus_comment_is_left_out_with_the_diagram(
    tmp_path: Path, keys: dict[str, object], note: str
) -> None:
    doc = _doc(tmp_path, "# Doc\n\n" + MERMAID + "The flow.\n\n<!-- narratty: focus b -->\n\nNext.\n")
    entry = MarkdownEntry.model_validate({"markdown": doc.name, **keys})
    expansion = explain_entry(entry, doc, entry.narration or "all")
    assert note in [n.what for n in expansion.notes]
    actions = [action for scene in expansion.scenes for action in scene.data.get("actions", [])]
    assert not any(action.get("slide", {}).get("focus") for action in actions)


def test_focus_comment_with_say_comments_and_narration_none(tmp_path: Path) -> None:
    body = (
        "# Doc\n\n" + MERMAID + "<!-- narratty: say The flow. -->\n\n"
        "<!-- narratty: focus b -->\n\n<!-- narratty: say The end. -->\n"
    )
    first, second = _expand(_doc(tmp_path, body), narration="none")
    assert [s.get("focus") for s in _slides(first) + _slides(second)] == [None, "b"]


@pytest.mark.parametrize("body", ["", "a b", "api.gateway", "{focus: a}", "a;b"])
def test_focus_comment_takes_one_id(tmp_path: Path, body: str) -> None:
    doc = "# Doc\n\n" + MERMAID + f"The flow.\n\n<!-- narratty: focus {body} -->\n"
    message, line = _error(tmp_path, doc)
    assert message.startswith("focus comment: expected one Mermaid node or subgraph ID")
    assert line == 9


def test_focus_comment_takes_ids_with_dashes_and_digits(tmp_path: Path) -> None:
    doc = "# Doc\n\n" + MERMAID + "The flow.\n\n<!-- narratty: focus api-gateway_2 -->\n\nNext.\n"
    scenes = _expand(_doc(tmp_path, doc))
    assert _slides(scenes[-1])[0]["focus"] == "api-gateway_2"


def test_ragged_markdown_tables_get_even_rows(tmp_path: Path) -> None:
    body = "# Doc\n\n<!-- narratty: slide -->\n| A | B |\n|---|---|\n| 1 |\n| 2 | 3 | 4 |\n\nRows.\n"
    (scene,) = _expand(_doc(tmp_path, body))
    assert _slides(scene)[0]["table"]["rows"] == [["1", ""], ["2", "3"]]


def test_slide_comment_shows_a_table_without_reading_it(tmp_path: Path) -> None:
    (scene,) = _expand(_doc(tmp_path, "# Doc\n\n<!-- narratty: slide -->\n" + SAFETY + "\nTwo risks.\n"))
    assert scene["narration"] == "Two risks."
    (slide,) = _slides(scene)
    assert "highlight" not in slide and len(slide["table"]["rows"]) == 2


def test_table_pages_follow_pause_comments(tmp_path: Path) -> None:
    rows = "".join(f"| r{n} |\n" for n in range(1, 6))
    body = (
        "# Doc\n\n<!-- narratty: slide {rows: 2} -->\n| R |\n|---|\n" + rows + "\nFirst two.\n\n"
        "<!-- narratty: pause 1s -->\n\nNext two.\n\n```bash\nls\n```\n"
    )
    scenes = _expand(_doc(tmp_path, body))
    shown = [([s.get("page") for s in _slides(scene)], scene.get("narration")) for scene in scenes]
    assert shown == [
        ([1], "First two."),
        ([2], None),  # the pause's silence already shows the next page
        ([2], "Next two."),
        ([3], None),  # left over: shown silently before the command
        ([], None),
    ]
    assert scenes[3]["actions"][1] == {"hold": 3000}


def test_slide_comment_shows_an_html_file(tmp_path: Path) -> None:
    (tmp_path / "slides").mkdir()
    (tmp_path / "slides" / "arch.html").write_text("<h1>Architecture</h1>", encoding="utf-8")
    body = "# Doc\n\nBefore.\n\n<!-- narratty: slide {html: slides/arch.html} -->\nThe parts.\n"
    before, scene = _expand(_doc(tmp_path, body))
    assert before["narration"] == "Before."
    (slide,) = _slides(scene)
    prefix = "data:text/html;base64,"
    assert base64.b64decode(slide["html"].removeprefix(prefix)).decode() == "<h1>Architecture</h1>"
    assert scene["narration"] == "The parts."


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("<!-- narratty: slide {html: missing.html} -->\n", "slide comment: file not found: missing.html"),
        (
            "<!-- narratty: slide -->\nText.\n",
            "slide comment: the next block is not a table, image or mermaid",
        ),
        ("<!-- narratty: slide {colour: red} -->\n" + MERMAID, "slide comment: unknown key 'colour'"),
    ],
)
def test_slide_comment_errors(tmp_path: Path, body: str, message: str) -> None:
    text, line = _error(tmp_path, "# Doc\n\n" + body)
    assert message in text
    assert line == 3


def test_slide_options_are_checked_with_the_spec(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "# Doc\n\n<!-- narratty: slide {rows: 2} -->\n" + MERMAID + "Text.\n")
    with pytest.raises(SpecError) as info:
        parse_document("scenes:\n  - markdown: doc.md\n", tmp_path / "s.narratty.yaml")
    (issue,) = info.value.issues
    assert "only apply to table slides" in issue.message
    assert (issue.file, issue.line) == (doc, 4)


def test_pages_too_large_to_embed(tmp_path: Path) -> None:
    (tmp_path / "big.html").write_bytes(b"x" * 1_600_000)
    message, _ = _error(tmp_path, "# Doc\n\n<!-- narratty: slide {html: big.html} -->\nText.\n")
    assert message == "big.html is too large to embed (Chromium loads data: URLs up to 2 MB)"


# ── per-block control ─────────────────────────────────────────────────────────


def test_say_before_types_once_the_text_is_spoken(tmp_path: Path) -> None:
    body = "# Doc\n\nList it.\n\n<!-- narratty: run {say: before} -->\n```console\n$ ls\n```\n"
    (scene,) = _expand(_doc(tmp_path, body))
    assert scene["narration"] == "List it."
    assert scene["actions"] == [{"hold": "auto"}, {"run": "ls"}, {"wait": {"prompt": True}}]
    attribute = '# Doc\n\nList it.\n\n```console {narratty="say=before"}\n$ ls\n```\n'
    assert _expand(_doc(tmp_path, attribute)) == [{**scene, "source": "doc.md:5"}]


def test_the_entry_can_say_before_every_block(tmp_path: Path) -> None:
    body = (
        '# Doc\n\n```console\n$ pwd\n```\n\nList it.\n\n```console {narratty="say=during"}\n$ ls\n```\n\n'
        "Again.\n\n```console\n$ ls\n```\n"
    )
    scenes = _expand(_doc(tmp_path, body), say="before")
    assert [scene["actions"][0] for scene in scenes] == [{"run": "pwd"}, {"run": "ls"}, {"hold": "auto"}]


def test_say_after_speaks_the_text_after_the_block_once_it_has_run(tmp_path: Path) -> None:
    body = (
        "# Doc\n\nFirst this.\n\n<!-- narratty: run {say: after} -->\n```console\n$ ls\n```\n\n"
        "It lists the files.\n\n<!-- narratty: say And more. -->\n\n## Next\n\nOther text.\n"
    )
    scenes = _expand(_doc(tmp_path, body))
    assert [(scene["id"], scene.get("narration"), scene.get("narration_start")) for scene in scenes] == [
        ("doc-1", "First this.", None),
        ("doc-2", "It lists the files. And more.", "after_actions"),
        ("doc-next-1", "Other text.", None),
    ]
    assert scenes[1]["actions"] == [{"run": "ls"}, {"wait": {"prompt": True}}]


def test_say_after_without_text_after(tmp_path: Path) -> None:
    body = '# Doc\n\n```console {narratty="say=after"}\n$ ls\n```\n\n```console\n$ pwd\n```\n'
    scenes = _expand(_doc(tmp_path, body))
    assert [(scene["id"], scene.get("narration_start")) for scene in scenes] == [
        ("doc-1", None),
        ("doc-2", None),
    ]


def test_instead_shows_the_readers_command_and_runs_another(tmp_path: Path) -> None:
    body = (
        "# Doc\n\n```console {narratty=\"instead='pip install -e .'\"}\n$ pip install tally\nInstalled\n```\n"
    )
    (scene,) = _expand(_doc(tmp_path, body))
    assert scene["actions"] == [
        {"run": "pip install -e .", "show": "pip install tally"},
        {"wait": {"prompt": True}},
    ]
    comment = '# Doc\n\n<!-- narratty: run {instead: "pip install -e ."} -->\n'
    comment += "```console\n$ pip install <pkg>\n```\n"
    assert _expand(_doc(tmp_path, comment))[0]["actions"][0]["show"] == "pip install <pkg>", (
        "placeholders are fine"
    )


def test_lines_cut_the_output_on_screen_but_check_compares_all(tmp_path: Path) -> None:
    body = '# Doc\n\n```console {narratty="lines=2"}\n$ seq 9\n1\n...\n$ ls\n```\n'
    (scene,) = _expand(_doc(tmp_path, body))
    assert scene["actions"] == [
        {"run": "seq 9", "max_lines": 2, "expect_output": "1\n..."},
        {"wait": {"prompt": True}},
        {"run": "ls", "max_lines": 2},
        {"wait": {"prompt": True}},
    ]


def test_until_stops_a_long_running_command_before_the_prompt_wait(tmp_path: Path) -> None:
    body = (
        "# Doc\n\n<!-- narratty: run {until: Serving HTTP, timeout: 10s} -->\n"
        "```console\n$ cd site\n$ python -m http.server\n```\n"
    )
    (scene,) = _expand(_doc(tmp_path, body))
    assert scene["actions"] == [
        {"run": "cd site"},
        {"wait": {"prompt": True}},
        {"run": "python -m http.server"},
        {"wait": {"screen": "Serving HTTP", "timeout_ms": 10000}},
        {"ctrl_sequence": "C-c"},
        {"wait": {"prompt": True}},
    ]
    less = "# Doc\n\n<!-- narratty: run {until: README, then: q} -->\n```console\n$ less README.md\n```\n"
    assert _expand(_doc(tmp_path, less))[0]["actions"][1:3] == [
        {"wait": {"screen": "README", "timeout_ms": 30000}},
        {"key": "q"},
    ]


def test_run_options_in_the_plan(tmp_path: Path) -> None:
    body = '# Doc\n\n```console {narratty="instead=true lines=3 until=x"}\n$ make\n```\n'
    entry = MarkdownEntry.model_validate({"markdown": "doc.md"})
    (note,) = explain_entry(entry, _doc(tmp_path, body), "all").notes
    assert note.what == (
        "console block: 1 command(s), shown, `true` runs instead, output cut after 3 lines, "
        "stopped once the screen matches /x/"
    )


@pytest.mark.parametrize(
    ("body", "message", "line"),
    [
        ("<!-- narratty: run {say: before} -->\nText.\n", "run comment: the next block is not a shell", 3),
        ("<!-- narratty: run {sai: before} -->\n```sh\nls\n```\n", "run comment: unknown key 'sai'", 3),
        (
            "<!-- narratty: run {say: later} -->\n```sh\nls\n```\n",
            "say must be one of before, during, after",
            3,
        ),
        ('```sh {narratty="then=C-d"}\nls\n```\n', "narratty attribute: then needs until", 3),
        ('```sh {narratty="lines=all"}\nls\n```\n', "lines must be a number of lines", 3),
        ('```sh {narratty="until=("}\nls\n```\n', "until is not a valid regular expression", 3),
        ('```sh {narratty="instead=true"}\nls\npwd\n```\n', "instead needs a block with one command", 3),
        ('```sh {narratty="no-run lines=3"}\nls\n```\n', "lines does not apply to no-run blocks", 3),
        ('```sh {narratty="hidden say=after"}\nls\n```\n', "say does not apply to hidden blocks", 3),
        ('```sh {narratty="speed=3"}\nls\n```\n', "unknown narratty option 'speed'", 3),
        ('```yaml {title="a.yaml" narratty="lines=3"}\na: 1\n```\n', "'lines=…' only applies to shell", 3),
    ],
)
def test_run_option_errors(tmp_path: Path, body: str, message: str, line: int) -> None:
    error, at = _error(tmp_path, "# Doc\n\n" + body)
    assert message in error
    assert at == line


def test_a_skipped_block_takes_its_run_comment_along(tmp_path: Path) -> None:
    body = "# Doc\n\n<!-- narratty: run {say: before} -->\n<!-- narratty: skip -->\n```sh\nls\n```\n\nText.\n"
    assert _expand(_doc(tmp_path, body))[0]["narration"] == "Text."


REAL = """\
# Doc

<!-- narratty: run {until: listening on, timeout: 5s} -->
```console
$ sh -c 'echo listening on 8000; sleep 60'
listening on 8000
...
```

```console {narratty="lines=2"}
$ seq 5
1
...
5
```

```console {narratty="no-run"}
$ rm -rf /
```

```console {narratty="instead='echo substituted'"}
$ pip install tally
```
"""


@pytest.mark.parametrize("unmask", [False, True], ids=["video", "check"])
def test_control_in_a_real_shell(tmp_path: Path, unmask: bool) -> None:
    from narratty.build import unmasked
    from narratty.render import exits, outputs
    from narratty.render.cast import record

    (tmp_path / "doc.md").write_text(REAL, encoding="utf-8")
    spec = parse_document(
        "terminal: {typing_speed_ms: 1}\nend_card: false\nscenes:\n  - markdown: doc.md\n",
        tmp_path / "s.narratty.yaml",
    ).spec
    spec = unmasked(spec) if unmask else spec
    log = tmp_path / "exits.log"
    log.write_text("", encoding="utf-8")
    steps = build_script(spec, build_timeline(spec, {}), exit_log=log)
    recording = record(steps, terminal=spec.terminal, cwd=tmp_path, env=os.environ, title="T", fast=True)
    entries = exits.parse_log(log.read_text(encoding="utf-8"))
    assert [entry.status for entry in entries] == [130, 0, 0, 0], "the server is stopped with C-c"
    assert exits.problems(spec, entries) == []
    printed = {item.line: outputs.plain_lines(item.output, "$ ") for item in recording.submitted}
    if unmask:
        assert outputs.problems(spec, recording.submitted) == [], "check sees all of the output"
        assert printed["seq 5"] == ["1", "2", "3", "4", "5"]
    else:
        trimmed = next(lines for line, lines in printed.items() if "seq 5" in line)
        assert trimmed[1:] == ["1", "2", "... (3 more lines)"], "after the redrawn command line"
        assert not any("rm -rf" in line for line in printed if not line.startswith("sh -c"))


def test_clear_comment_clears_the_screen_with_the_next_scene(tmp_path: Path) -> None:
    body = "# Doc\n\nBefore.\n\n<!-- narratty: clear -->\n\n<!-- narratty: hidden\ncd /tmp\n-->\n\n"
    body += "After.\n\n```sh\nls\n```\n"
    scenes = _expand(_doc(tmp_path, body))
    assert [(scene["id"], scene.get("narration"), scene.get("actions", [])[:1]) for scene in scenes] == [
        ("doc-1", "Before.", []),
        ("doc-2", None, [{"run": "cd /tmp"}]),
        ("doc-3", "After.", [{"ctrl_sequence": "C-l"}]),
    ], "the hidden scene leaves it to the next visible one"


def test_clear_on_clears_at_each_section_with_its_heading_overlay(tmp_path: Path) -> None:
    body = (
        '# Doc\n\nIntro.\n\n## A\n\n### A1\n\nText.\n\n## B\n\n```sh {narratty="hidden"}\nls\n```\n\nMore.\n'
    )
    scenes = _expand(_doc(tmp_path, body), clear_on=2, heading_overlays=2)
    assert [(scene["id"], scene.get("actions")) for scene in scenes] == [
        ("doc-1", [{"ctrl_sequence": "C-l"}, {"overlay": {"text": "Doc", "style": "heading-1"}}]),
        ("doc-a1-1", [{"ctrl_sequence": "C-l"}, {"overlay": {"text": "A", "style": "heading-2"}}]),
        ("doc-b-1", [{"run": "ls"}, {"wait": {"prompt": True}}]),
        ("doc-b-2", [{"ctrl_sequence": "C-l"}, {"overlay": {"text": "B", "style": "heading-2"}}]),
    ]


def test_clear_comment_takes_no_value(tmp_path: Path) -> None:
    assert (
        _error(tmp_path, "# Doc\n\n<!-- narratty: clear all -->\n")[0]
        == "clear comment: takes no value, got 'all'"
    )


HELD = """\
# Doc

<!-- narratty: slide {title: Parts, hold: HOLD} -->
| Part | Does |
|---|---|
| A | a |

The first part.

<!-- narratty: pause 500ms -->

The second part.

<!-- narratty: pause -->

A command.

```sh
ls
```

After the command.

## Next

Elsewhere.
"""


def _slide_titles(scenes: list[dict[str, Any]]) -> list[tuple[str | None, str | None]]:
    return [
        (
            scene.get("narration"),
            next((a["slide"]["title"] for a in scene.get("actions", []) if "slide" in a), None),
        )
        for scene in scenes
    ]


def test_a_held_slide_stays_for_the_text_up_to_the_next_block(tmp_path: Path) -> None:
    scenes = _expand(_doc(tmp_path, HELD.replace("HOLD", "next-block")))
    assert _slide_titles(scenes) == [
        ("The first part.", "Parts"),
        (None, "Parts"),
        ("The second part.", "Parts"),
        ("A command.", None),
        ("After the command.", None),
        ("Elsewhere.", None),
    ]
    assert scenes[1]["actions"][1] == {"hold": 500}
    assert _slide_titles(_expand(_doc(tmp_path, HELD.replace(", hold: HOLD", ""))))[1:3] == [
        (None, None),
        ("The second part.", None),
    ], "without hold, as before"


def test_a_slide_held_to_the_next_heading_comes_back_after_commands(tmp_path: Path) -> None:
    scenes = _expand(_doc(tmp_path, HELD.replace("HOLD", "next-heading")))
    after = [("A command.", None), ("After the command.", "Parts"), ("Elsewhere.", None)]
    assert _slide_titles(scenes)[3:] == after


def test_a_read_table_can_stay_after_its_rows(tmp_path: Path) -> None:
    body = (
        "# Doc\n\n<!-- narratty: table {title: T, hold: next-block} -->\n"
        "| A | B |\n|---|---|\n| 1 | 2 |\n\nAfter the table.\n"
    )
    scenes = _expand(_doc(tmp_path, body))
    assert scenes[-1]["narration"] == "After the table."
    assert scenes[-1]["actions"] == [
        {"slide": {"title": "T", "table": {"header": ["A", "B"], "rows": [["1", "2"]]}}}
    ]


def test_hold_must_name_a_block_or_heading(tmp_path: Path) -> None:
    message, _ = _error(tmp_path, "# Doc\n\n<!-- narratty: slide {hold: forever} -->\n![x](x.png)\n")
    assert message == "slide comment: hold must be next-block or next-heading, got 'forever'"


def test_yaml_errors_in_comments_hint_at_quoting(tmp_path: Path) -> None:
    from narratty.spec.loader import SCHEMA_HINT, SpecError, load_spec

    doc = tmp_path / "doc.md"
    doc.write_text("# Doc\n\n<!-- narratty: overlay {text: GET /orders/{id}} -->\n\n```bash\nls\n```\n")
    with pytest.raises(SpecError) as raised:
        load_spec(doc)
    assert "invalid YAML" in raised.value.message
    assert raised.value.hint and "Quote" in raised.value.hint and "schema" not in raised.value.hint
    doc.write_text("# Doc\n\n<!-- narratty: overlay {text: hi, colour: red} -->\n\n```bash\nls\n```\n")
    with pytest.raises(SpecError) as raised:
        load_spec(doc)
    assert raised.value.hint is None, "the schema lists YAML keys, not Markdown comments"
    assert SCHEMA_HINT not in raised.value.message


@pytest.mark.parametrize(
    ("comment", "overlay"),
    [
        ("not run: in this video", "not run: in this video"),
        ("{text: Hi, style: note}", {"text": "Hi", "style": "note"}),
        ("Plain text", "Plain text"),
        ("[a, b", "[a, b"),
    ],
)
def test_overlay_comment_text_may_contain_a_colon(tmp_path: Path, comment: str, overlay: object) -> None:
    body = f"# Doc\n\n<!-- narratty: overlay {comment} -->\nSaid.\n"
    (scene,) = _expand(_doc(tmp_path, body))
    assert scene["actions"][0] == {"overlay": overlay}


def test_markdown_errors_have_no_schema_hint(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "# Doc\n\n```bash\ngit clone <repo-url>\n```\n")
    with pytest.raises(SpecError) as info:
        _expand(doc)
    assert "narratty schema" not in (info.value.hint or "")
