"""validate, schema and init commands."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from narratty.cli.app import app
from narratty.errors import ExitCode, UsageError
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


def test_init_refuses_to_overwrite(tmp_path: Path) -> None:
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text("keep", encoding="utf-8")
    result = runner.invoke(app, ["init", str(spec)])
    assert isinstance(result.exception, UsageError)
    assert spec.read_text(encoding="utf-8") == "keep"
    assert runner.invoke(app, ["init", str(spec), "--force"]).exit_code == 0


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
