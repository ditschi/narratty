"""``narratty validate`` warnings about Markdown docs."""

from __future__ import annotations

from pathlib import Path

import pytest

from narratty.spec.markdown import lint_entry
from narratty.spec.markdown.lint import mermaid_targets
from narratty.spec.model import MarkdownEntry

RUN = "```console\n$ ls\n```\n"


def _warnings(tmp_path: Path, body: str, **keys: object) -> list[tuple[int, str]]:
    doc = tmp_path / "doc.md"
    doc.write_text(body, encoding="utf-8")
    entry = MarkdownEntry.model_validate({"markdown": doc.name, **keys})
    return [(note.line, note.what) for note in lint_entry(entry, doc, "all")]


def test_a_plain_doc_has_no_warnings(tmp_path: Path) -> None:
    assert _warnings(tmp_path, "# Doc\n\nList the files.\n\n" + RUN) == []


def test_no_commands(tmp_path: Path) -> None:
    ((line, what),) = _warnings(tmp_path, "# Doc\n\nOnly text.\n")
    assert line == 1
    assert what.startswith("no command runs in the video")
    assert _warnings(tmp_path, '# Doc\n\n```console {narratty="no-run"}\n$ pip install x\n```\n') == []


@pytest.mark.parametrize("lang", ["", "text", "shell-session"])
def test_left_out_blocks_with_prompts(tmp_path: Path, lang: str) -> None:
    ((line, what),) = _warnings(tmp_path, f"# Doc\n\n```{lang}\n$ make install\n```\n\n" + RUN)
    assert line == 3
    assert "label it `console`" in what


def test_tables_without_a_comment(tmp_path: Path) -> None:
    table = "| a |\n|---|\n| b |\n"
    ((line, what),) = _warnings(tmp_path, "# Doc\n\n" + table + "\n" + RUN)
    assert (line, what.split(";")[0]) == (3, "table left out of the video")
    assert _warnings(tmp_path, "# Doc\n\n<!-- narratty: skip -->\n" + table + "\n" + RUN) == []


@pytest.mark.parametrize(
    "output",
    [
        "error: no such file",
        "Error: missing",
        "fatal: not a git repository",
        "Traceback (most recent call last):",
    ],
)
def test_error_output_without_expect_failure(tmp_path: Path, output: str) -> None:
    block = f"```console\n$ ls\nfine\n{output}\n```\n"
    ((line, what),) = _warnings(tmp_path, "# Doc\n\n" + block)
    assert line == 6
    assert 'add narratty="expect-failure"' in what
    marked = block.replace("console", 'console {narratty="expect-failure"}')
    assert _warnings(tmp_path, "# Doc\n\n" + marked) == []


def test_no_error_warning_for_ordinary_output(tmp_path: Path) -> None:
    assert _warnings(tmp_path, "# Doc\n\n```console\n$ ls\nerrors.log\nno errors: 0\n```\n") == []


FLOW = "```mermaid\nflowchart LR\n  api[API] --> db[(Database)]\n```\n\nThe API.\n\n"


def test_focus_comment_ids_are_checked(tmp_path: Path) -> None:
    body = "# Doc\n\n" + FLOW + "<!-- narratty: focus dbb -->\nThe database.\n\n" + RUN
    assert _warnings(tmp_path, body) == [
        (10, "focus 'dbb' is not a node or subgraph of the Mermaid diagram at line 3 (did you mean 'db'?)")
    ]
    assert _warnings(tmp_path, body.replace("dbb", "db")) == []


def test_slide_comment_focus_is_checked(tmp_path: Path) -> None:
    body = "# Doc\n\n<!-- narratty: slide {focus: apii} -->\n" + FLOW + RUN
    ((line, what),) = _warnings(tmp_path, body)
    assert line == 3
    assert "did you mean 'api'" in what


def test_sequence_participants_can_be_focused(tmp_path: Path) -> None:
    diagram = (
        "```mermaid\nsequenceDiagram\n  participant C as Client\n  actor U\n  C->>S: request\n```\n"
        "\nIt asks.\n\n"
    )
    body = f"# Doc\n\n{diagram}<!-- narratty: focus S -->\nThe server.\n\n{RUN}"
    assert _warnings(tmp_path, body) == []
    ((_, what),) = _warnings(tmp_path, body.replace("focus S", "focus Client"))
    assert what.startswith("focus 'Client' is not a participant")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("flowchart LR\n  a --> b", {"a", "b"}),
        (
            "graph TD\n  api-gateway[Gateway] -->|calls| api\n  subgraph backend [Back end]\n  db\n  end",
            {"api-gateway", "api", "backend", "db"},
        ),
        ('flowchart LR\n  a("x y") -.-> b{{z}}:::hot\n  s@{ shape: stadium, label: Q }', {"a", "b", "s"}),
    ],
)
def test_flowchart_ids(source: str, expected: set[str]) -> None:
    targets = mermaid_targets(source)
    assert targets is not None
    assert targets[1] == expected


def test_other_diagram_types_are_not_checked() -> None:
    assert mermaid_targets("classDiagram\n  A <|-- B") is None


def test_spatial_words_in_narration(tmp_path: Path) -> None:
    body = "# Doc\n\nRun the following command.\n\n<!-- narratty: say As shown above. -->\n\n" + RUN
    assert [line for line, _ in _warnings(tmp_path, body)] == [3, 5]
    skipped = "# Doc\n\n<!-- narratty: skip -->\nClick here.\n\nThe aboveground cable.\n\n" + RUN
    assert _warnings(tmp_path, skipped) == []


def test_only_the_selected_sections_are_checked(tmp_path: Path) -> None:
    body = "# Doc\n\n" + RUN + "\n## FAQ\n\nSee below.\n"
    assert _warnings(tmp_path, body, sections={"exclude": ["faq"]}) == []
    assert len(_warnings(tmp_path, body)) == 1


def test_lint_false_turns_warnings_off(tmp_path: Path) -> None:
    assert _warnings(tmp_path, "# Doc\n\nSee below.\n", lint=False) == []
