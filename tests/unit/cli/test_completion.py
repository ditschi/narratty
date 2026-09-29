"""Shell completion is wired up and completes subcommands and runtimes."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from narratty.cli.app import app
from narratty.cli.completion import complete_spec_path
from tests.helpers import plain

runner = CliRunner()


def _complete_bash(words: str, cword: int) -> list[str]:
    result = runner.invoke(
        app,
        [],
        prog_name="narratty",
        env={"_NARRATTY_COMPLETE": "complete_bash", "COMP_WORDS": words, "COMP_CWORD": str(cword)},
    )
    assert result.exit_code == 0, result.output
    return result.output.split()


def test_completes_subcommands() -> None:
    assert "doctor" in _complete_bash("narratty do", 1)


def test_completes_runtime_values() -> None:
    assert set(_complete_bash("narratty doctor --runtime ", 3)) == {"auto", "native", "docker", "podman"}


def test_show_completion_is_available() -> None:
    result = runner.invoke(app, ["--help"])
    assert "--install-completion" in plain(result.output)


def test_completes_spec_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "demo.narratty.yaml").write_text("", encoding="utf-8")
    (tmp_path / "other.yaml").write_text("", encoding="utf-8")
    (tmp_path / "examples").mkdir()
    (tmp_path / ".hidden").mkdir()
    monkeypatch.chdir(tmp_path)
    assert complete_spec_path("") == ["demo.narratty.yaml", "examples/"]
    assert complete_spec_path("ex") == ["examples/"]
    (tmp_path / "examples" / "tour.narratty.yml").write_text("", encoding="utf-8")
    assert complete_spec_path("examples/") == ["examples/tour.narratty.yml"]
    assert complete_spec_path("missing/") == []


def test_validate_completes_spec_argument(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "demo.narratty.yaml").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert "demo.narratty.yaml" in _complete_bash("narratty validate ", 2)
