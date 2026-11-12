"""validate, schema and init commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from narratty.cli.app import app
from narratty.errors import ExitCode, OutputError, UsageError
from narratty.spec import SpecError
from tests.helpers import plain

runner = CliRunner()


def test_init_then_validate(tmp_path: Path) -> None:
    spec = tmp_path / "demo.narratty.yaml"
    assert runner.invoke(app, ["init", str(spec)]).exit_code == 0
    result = runner.invoke(app, ["validate", str(spec)])
    assert result.exit_code == 0, result.output
    assert "2 scenes, 2 narrated" in plain(result.output)


def test_validate_prints_hints(tmp_path: Path) -> None:
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text("terminal: {width: 1200}\nscenes:\n  - id: a\n", encoding="utf-8")
    result = runner.invoke(app, ["validate", str(spec)])
    assert result.exit_code == 0, result.output
    assert "terminal.width: same as the default; leave it out" in plain(result.output)


def test_validate_warns_about_markdown_docs(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("# Doc\n\nThe table below.\n\n| a |\n|---|\n| b |\n", encoding="utf-8")
    result = runner.invoke(app, ["validate", str(doc)])
    assert result.exit_code == 0, result.output
    output = plain(result.output)
    assert f"warning: {doc}:1:1: no command runs in the video" in output
    assert f"warning: {doc}:3:1: the narration says 'below'" in output
    assert f"warning: {doc}:5:1: table left out of the video" in output
    doc.write_text("<!-- narratty: spec\nlint: false\n-->\n# Doc\n\nThe table below.\n", encoding="utf-8")
    assert "warning" not in plain(runner.invoke(app, ["validate", str(doc)]).output)


def test_init_refuses_to_overwrite(tmp_path: Path) -> None:
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text("keep", encoding="utf-8")
    result = runner.invoke(app, ["init", str(spec)])
    assert isinstance(result.exception, UsageError)
    assert spec.read_text(encoding="utf-8") == "keep"
    assert runner.invoke(app, ["init", str(spec), "--force"]).exit_code == 0


def test_init_for_a_markdown_doc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n\nSay this.\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--markdown", "docs/guide.md"])
    assert result.exit_code == 0, result.output
    spec = tmp_path / "guide.narratty.yaml"
    assert "  - markdown: docs/guide.md\n" in spec.read_text(encoding="utf-8")
    result = runner.invoke(app, ["validate", str(spec)])
    assert result.exit_code == 0, result.output
    assert "hint" not in plain(result.output)
    result = runner.invoke(app, ["init", "--markdown", "missing.md"])
    assert isinstance(result.exception, UsageError)


def test_a_markdown_doc_is_a_spec(tmp_path: Path) -> None:
    doc = tmp_path / "guide.md"
    doc.write_text("# Guide\n\nSay this.\n\n```bash\nls\n```\n", encoding="utf-8")
    result = runner.invoke(app, ["validate", str(doc)])
    assert result.exit_code == 0, result.output
    assert "1 scenes, 1 narrated" in plain(result.output)
    result = runner.invoke(app, ["compile", str(doc)])
    assert result.output.startswith("scenes:\n  # from guide.md:5\n  - id: guide-1\n")


def test_check_compares_output(tmp_path: Path) -> None:
    doc = tmp_path / "guide.md"
    doc.write_text("# Guide\n\n```console\n$ echo hi\nhi\n```\n", encoding="utf-8")
    args = ["check", str(doc), "--runtime", "native", "--workspace-mode", "rw"]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "1 command ran; 1 output as expected" in plain(result.output)
    doc.write_text("# Guide\n\n```console\n$ echo hi\nho\n```\n", encoding="utf-8")
    result = runner.invoke(app, args)
    assert isinstance(result.exception, OutputError)
    assert result.exception.exit_code is ExitCode.OUTPUT


def test_validate_reports_problems(tmp_path: Path) -> None:
    spec = tmp_path / "bad.narratty.yaml"
    spec.write_text("scenes:\n  - id: a\n    hiden: true\n", encoding="utf-8")
    result = runner.invoke(app, ["validate", str(spec)])
    assert isinstance(result.exception, SpecError)
    assert result.exception.exit_code is ExitCode.VALIDATION


def test_schema_prints_json() -> None:
    result = runner.invoke(app, ["schema"])
    assert result.exit_code == 0
    assert json.loads(result.output)["title"] == "narratty spec"


def _markdown_spec(tmp_path: Path) -> Path:
    (tmp_path / "doc.md").write_text(
        "# Doc\n\nSay this.\n\n```bash\nls\n```\n\n```yaml\na: 1\n```\n", encoding="utf-8"
    )
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text("scenes:\n  - id: intro  # kept\n  - markdown: doc.md\n", encoding="utf-8")
    return spec


def test_compile_expands_markdown_entries(tmp_path: Path) -> None:
    spec = _markdown_spec(tmp_path)
    result = runner.invoke(app, ["compile", str(spec)])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("scenes:\n  - id: intro  # kept\n  # from doc.md:5\n  - id: doc-1\n")
    compiled = tmp_path / "compiled.narratty.yaml"
    assert runner.invoke(app, ["compile", str(spec), "-o", str(compiled)]).exit_code == 0
    assert runner.invoke(app, ["validate", str(compiled)]).exit_code == 0


def test_plan_sources(tmp_path: Path) -> None:
    result = runner.invoke(app, ["plan", "--sources", str(_markdown_spec(tmp_path))])
    assert result.exit_code == 0, result.output
    text = plain(result.output)
    for expected in (
        "YAML scene",
        "paragraph: spoken",
        "bash block: 1 command(s), run",
        "yaml block",
    ):
        assert expected in text
