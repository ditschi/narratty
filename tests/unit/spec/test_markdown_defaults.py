"""Defaults for common Markdown: footnotes, task lists, callouts, code slides, sections."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from narratty.spec import SpecError
from narratty.spec.markdown import EntryError, expand_entry, explain_entry
from narratty.spec.model import MarkdownEntry, Spec

FIXTURES = Path(__file__).parent / "markdown"


def _doc(tmp_path: Path, body: str) -> Path:
    doc = tmp_path / "doc.md"
    doc.write_text(body, encoding="utf-8")
    return doc


def _expand(path: Path, **keys: object) -> list[dict[str, Any]]:
    entry = MarkdownEntry.model_validate({"markdown": path.name, **keys})
    return [scene.data for scene in expand_entry(entry, path, entry.narration or "all")]


def _notes(path: Path, **keys: object) -> list[tuple[int, str | None, str]]:
    entry = MarkdownEntry.model_validate({"markdown": path.name, **keys})
    return [(note.line, note.scene, note.what) for note in explain_entry(entry, path, "all").notes]


def _narration(tmp_path: Path, body: str, **keys: object) -> list[str]:
    return [scene.get("narration", "") for scene in _expand(_doc(tmp_path, body), **keys)]


def _slides(scene: dict[str, Any]) -> list[dict[str, Any]]:
    return [action["slide"] for action in scene.get("actions", []) if "slide" in action]


# ── footnotes ─────────────────────────────────────────────────────────────────

FOOTNOTES = (
    "# Doc\n\nThe cache is shared[^share]. It is pruned weekly[^prune] by a job.\n\n"
    "[^share]: Between all builds\n    on the host.\n[^prune]: See the cron job.\n"
)


def test_footnote_markers_and_definitions_are_not_spoken(tmp_path: Path) -> None:
    assert _narration(tmp_path, FOOTNOTES) == ["The cache is shared. It is pruned weekly by a job."]
    notes = _notes(tmp_path / "doc.md")
    assert (5, None, "footnote definition: not spoken (footnotes: skip)") in notes
    assert (7, None, "footnote definition: not spoken (footnotes: skip)") in notes


def test_inline_footnotes_follow_their_sentence(tmp_path: Path) -> None:
    assert _narration(tmp_path, FOOTNOTES, footnotes="inline") == [
        "The cache is shared. Between all builds on the host. It is pruned weekly by a job. See the cron job."
    ]


def test_inline_footnote_at_the_end_of_a_list_item(tmp_path: Path) -> None:
    body = "# Doc\n\n- An item[^a]\n\n[^a]: Its note\n"
    assert _narration(tmp_path, body, footnotes="inline") == ["An item. Its note."]


# ── task lists ────────────────────────────────────────────────────────────────


def test_task_list_boxes_are_not_spoken(tmp_path: Path) -> None:
    body = "# Doc\n\n- [ ] Install uv\n- [x] Clone the repo\n- [link] stays\n"
    assert _narration(tmp_path, body) == ["Install uv. Clone the repo. [link] stays."]


# ── admonitions and alerts ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("body", "spoken"),
    [
        ('!!! warning "Cache keys"\n    Keys change.\n', "Warning: Cache keys. Keys change."),
        ("!!! danger\n    Data is lost.\n", "Danger: Data is lost."),
        ('!!! warning "Warning"\n    Keys change.\n', "Warning: Keys change."),
        ("???+ caution\n    Open collapsible.\n", "Caution: Open collapsible."),
        ("> [!IMPORTANT]\n> Read this.\n", "Important: Read this."),
        ("> [!NOTE]\n> Just a note.\n", "Just a note."),
        ('!!! tip "Short"\n    A tip.\n', "A tip."),
        ("!!! warning\n    ```bash\n    ls\n    ```\n", "Warning."),
    ],
)
def test_warnings_say_their_type(tmp_path: Path, body: str, spoken: str) -> None:
    assert _narration(tmp_path, "# Doc\n\n" + body)[0] == spoken


def test_admonition_templates_per_type(tmp_path: Path) -> None:
    body = '# Doc\n\n!!! tip "Speed"\n    Use the cache.\n\n!!! warning\n    Careful.\n'
    templates = {"tip": "{type}, {title}: {body}", "warning": "{body}"}
    assert _narration(tmp_path, body, admonitions=templates) == ["Tip, Speed: Use the cache. Careful."]
    assert _narration(tmp_path, body, admonitions=False) == ["Use the cache. Careful."]


def test_admonition_template_fields_are_checked() -> None:
    with pytest.raises(ValueError, match=r"unknown field \{text\}"):
        MarkdownEntry.model_validate({"markdown": "a.md", "admonitions": {"tip": "{text}"}})


# ── shown-only code ───────────────────────────────────────────────────────────


def test_show_makes_a_code_slide_while_the_text_is_spoken(tmp_path: Path) -> None:
    body = (
        "# Doc\n\nThe API answers:\n\n"
        '```json {narratty="show"}\n{"status": "ok"}\n```\n\n'
        "The status is ok.\n\n```bash\nls\n```\n"
    )
    shown, command = _expand(_doc(tmp_path, body))
    assert shown["narration"] == "The API answers: The status is ok."
    assert _slides(shown) == [{"code": '{"status": "ok"}', "lang": "json"}]
    assert command["actions"][0] == {"run": "ls"}
    assert (5, "doc-1", "json block: shown as a slide") in _notes(tmp_path / "doc.md")


def test_show_takes_the_slide_comment_and_title(tmp_path: Path) -> None:
    body = (
        "# Doc\n\n<!-- narratty: slide {theme: light} -->\n"
        '```yaml {title="compose.yaml" narratty="show"}\nservices: {}\n```\n'
    )
    (scene,) = _expand(_doc(tmp_path, body))
    assert _slides(scene) == [
        {"title": "compose.yaml", "theme": "light", "code": "services: {}", "lang": "yaml"}
    ]
    assert not any("run" in action for action in scene["actions"]), "no file is written"
    Spec.model_validate({"scenes": [scene]})


@pytest.mark.parametrize(
    ("block", "message"),
    [
        ('```json {narratty="show hidden"}\n{}\n```\n', "'hidden' does not apply to blocks marked show"),
        ('```json {narratty="show"}\n\n```\n', "the block marked show is empty"),
    ],
)
def test_show_errors(tmp_path: Path, block: str, message: str) -> None:
    doc = _doc(tmp_path, "# Doc\n\n" + block)
    with pytest.raises(SpecError) as info:
        _expand(doc)
    assert info.value.issues[0].message == message


@pytest.mark.parametrize(
    ("block", "what"),
    [
        ("```\nplain\n```\n", "code block: left out (no language)"),
        ("```json\n{}\n```\n", 'json block: left out (no title; add a title or narratty="show")'),
    ],
)
def test_left_out_blocks_say_how_to_keep_them(tmp_path: Path, block: str, what: str) -> None:
    assert (3, None, what) in _notes(_doc(tmp_path, "# Doc\n\n" + block))


def test_inline_images_and_badges_are_listed(tmp_path: Path) -> None:
    body = "# Doc\n\n[![CI](https://x/badge.svg)](https://x) Build status.\n"
    notes = _notes(_doc(tmp_path, body))
    assert (3, None, "image: left out (inline image)") in notes
    assert (3, "doc-1", "paragraph: spoken") in notes


# ── images ────────────────────────────────────────────────────────────────────


def _image_doc(tmp_path: Path, body: str) -> Path:
    (tmp_path / "pic.png").write_bytes((FIXTURES / "image.png").read_bytes())
    return _doc(tmp_path, "# Doc\n\n" + body)


def test_alt_text_titles_the_image_slide(tmp_path: Path) -> None:
    (scene,) = _expand(_image_doc(tmp_path, "![The overlays](pic.png)\n"))
    assert _slides(scene)[0]["title"] == "The overlays"
    (scene,) = _expand(_image_doc(tmp_path, "![The overlays](pic.png)\n"), image_titles=False)
    assert "title" not in _slides(scene)[0]
    body = "<!-- narratty: slide {title: Mine} -->\n![The overlays](pic.png)\n"
    (scene,) = _expand(_image_doc(tmp_path, body))
    assert _slides(scene)[0]["title"] == "Mine"
    (scene,) = _expand(_image_doc(tmp_path, "![](pic.png)\n"))
    assert "title" not in _slides(scene)[0]


# ── sections ──────────────────────────────────────────────────────────────────

GUIDE = (
    "# Guide\n\nIntro.\n\n## Install\n\nInstall it.\n\n### Extras\n\nExtras.\n\n"
    "## FAQ\n\nQuestions.\n\n## Next\n\nNext steps.\n"
)


def test_exclude_keeps_the_intro(tmp_path: Path) -> None:
    doc = _doc(tmp_path, GUIDE)
    assert _narration(tmp_path, GUIDE, sections={"exclude": ["faq"]}) == [
        "Intro.",
        "Install it.",
        "Extras.",
        "Next steps.",
    ]
    narration = [scene["narration"] for scene in _expand(doc, sections={"exclude": ["extras", "next"]})]
    assert narration == ["Intro.", "Install it.", "Questions."]


def test_include_and_exclude(tmp_path: Path) -> None:
    sections = {"include": ["install", "next"], "exclude": ["extras"]}
    assert _narration(tmp_path, GUIDE, sections=sections) == ["Install it.", "Next steps."]


def test_unknown_excluded_section(tmp_path: Path) -> None:
    with pytest.raises(EntryError) as info:
        _expand(_doc(tmp_path, GUIDE), sections={"exclude": ["fqa"]})
    assert info.value.loc == ("sections", "exclude", 0)
    assert "did you mean 'faq'" in info.value.message


def test_skip_rest_leaves_out_the_rest_of_the_section(tmp_path: Path) -> None:
    body = GUIDE.replace("Install it.\n", "Install it.\n\n<!-- narratty: skip-rest -->\n\nOnly readers.\n")
    assert _narration(tmp_path, body) == ["Intro.", "Install it.", "Questions.", "Next steps."]
    notes = _notes(tmp_path / "doc.md")
    assert (9, None, "skip-rest comment: the rest of the section is left out") in notes
    assert (11, None, "paragraph: left out by a skip-rest comment") in notes
    assert (13, None, "heading: left out by a skip-rest comment") in notes


def test_skip_rest_before_the_first_heading(tmp_path: Path) -> None:
    body = "Badges and links.\n\n<!-- narratty: skip-rest -->\n\nMore.\n\n# Title\n\nSpoken.\n"
    assert _narration(tmp_path, body) == ["Badges and links.", "Spoken."]


def test_skip_before_a_heading_is_reported_as_the_heading(tmp_path: Path) -> None:
    body = "# Doc\n\n<!-- narratty: skip -->\n## Part\n\nSpoken.\n"
    assert _narration(tmp_path, body, heading_overlays=2) == ["Spoken."]
    (scene,) = _expand(tmp_path / "doc.md", heading_overlays=2)
    assert scene["actions"] == [{"overlay": {"text": "Doc", "style": "heading-1"}}], "no 'Part' overlay"
    assert (4, None, "heading: left out by a skip comment (no overlay)") in _notes(tmp_path / "doc.md")


# ── table lead-in ─────────────────────────────────────────────────────────────

TABLE = "| Step | Does |\n|---|---|\n| Check | validates |\n| Build | renders |\n"


def test_a_lead_in_ending_with_a_colon_is_spoken_with_the_table(tmp_path: Path) -> None:
    body = "# Doc\n\nFirst.\n\nThe steps are:\n\n<!-- narratty: table -->\n" + TABLE
    scenes = _expand(_doc(tmp_path, body))
    assert [scene["narration"] for scene in scenes] == [
        "First.",
        "The steps are: Step: Check. Does: validates.",
        "Step: Build. Does: renders.",
    ]
    assert _slides(scenes[1])[0]["highlight"] == 1
    assert (5, "doc-2", "paragraph: spoken with the table's first row") in _notes(tmp_path / "doc.md")


def test_other_paragraphs_before_a_table_stay_before_it(tmp_path: Path) -> None:
    body = "# Doc\n\nThe steps follow.\n\n<!-- narratty: table -->\n" + TABLE
    assert _narration(tmp_path, body)[0] == "The steps follow."


def test_a_lead_in_must_stand_right_before_the_table(tmp_path: Path) -> None:
    body = "# Doc\n\nThe snippet:\n\n```markdown\nx\n```\n\n<!-- narratty: table -->\n" + TABLE
    assert _narration(tmp_path, body)[0] == "The snippet:"


def test_section_filter_errors_name_one_form(tmp_path: Path) -> None:
    from narratty.spec.loader import parse_document

    _doc(tmp_path, GUIDE)
    with pytest.raises(SpecError) as info:
        parse_document(
            "scenes:\n  - markdown: doc.md\n    sections: {exclud: [faq]}\n", tmp_path / "s.narratty.yaml"
        )
    (issue,) = info.value.issues
    assert issue.message == "unknown key 'exclud' (did you mean 'exclude'?)"
