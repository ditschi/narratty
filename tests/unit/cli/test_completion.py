"""Shell completion is wired up and completes subcommands and runtimes."""

from __future__ import annotations

from typer.testing import CliRunner

from narratty.cli.app import app
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
