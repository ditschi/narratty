"""CLI wiring: version, help, doctor exit codes."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from narratty import __version__
from narratty.cli.app import app
from narratty.errors import ExitCode, MissingDependencyError

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"narratty {__version__}"


def test_no_args_shows_help() -> None:
    result = runner.invoke(app, [])
    assert "doctor" in result.output


def test_doctor_passes_when_tools_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    result = runner.invoke(app, ["doctor", "--runtime", "native"])
    assert result.exit_code == 0, result.output
    assert "runtime: native" in result.output


def test_doctor_reports_missing_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None if name == "ffmpeg" else f"/usr/bin/{name}")
    result = runner.invoke(app, ["doctor", "--runtime", "native"])
    assert isinstance(result.exception, MissingDependencyError)
    assert result.exception.exit_code is ExitCode.MISSING_DEPENDENCY
    assert "ffmpeg" in result.exception.message


def test_runtime_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    result = runner.invoke(app, ["doctor"], env={"NARRATTY_RUNTIME": "podman"})
    assert result.exit_code == 0, result.output
    assert "runtime: podman" in result.output
