"""Commands typed into the demo's terminal."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from narratty import sh

SHELLS = [s for s in ("sh", "dash", "bash", "zsh", "fish") if shutil.which(s)]


def _run(shell: str, command: str) -> str:
    return subprocess.run([shell, "-c", command], capture_output=True, text=True, check=True).stdout


@pytest.mark.parametrize("shell", ["sh", "dash", "bash"])
@pytest.mark.parametrize(
    "text", ["plain.txt", "a b", "it's", 'say "hi"', "50%", "$HOME `x` #1", "ä€", "back\\slash"]
)
def test_word_survives_every_quoting_level(shell: str, text: str) -> None:
    if not shutil.which(shell):
        pytest.skip(f"needs {shell}")
    assert _run(shell, f'printf "%s" {sh.word(text)}') == text


def test_hidden_word_does_not_contain_the_text() -> None:
    assert "Terminal" not in sh.hidden_word("Terminal")
    assert _run("sh", f'printf "%s" {sh.hidden_word("Terminal")}') == "Terminal"


@pytest.mark.parametrize("shell", SHELLS)
def test_command_runs_the_same_from_any_shell(shell: str) -> None:
    command = sh.command(f'printf "%s" {sh.word("it's 100%")}')
    assert _run(shell, command) == "it's 100%"


def test_unsafe_scripts_are_refused() -> None:
    with pytest.raises(ValueError, match="not safe to type"):
        sh.command("echo 'x'")
    with pytest.raises(ValueError, match="not safe to type"):
        sh.tmux_arg("echo #x")


def test_need_names_the_missing_tool_and_where() -> None:
    script = sh.need(["definitely-not-a-tool"], "the editor layout", "in the project environment")
    result = subprocess.run(["sh", "-c", script], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert (
        sh.error_in(result.stderr)
        == "the editor layout needs definitely-not-a-tool in the project environment"
    )


def test_the_typed_command_itself_never_looks_like_an_error() -> None:
    typed = sh.command(sh.need(["x"], "the diff action", "here"))
    assert sh.error_in(typed) is None


def test_the_recorders_echo_of_the_wait_pattern_is_not_an_error() -> None:
    log = (
        f"Wait+Screen@1000ms /(diff baseline ready)|({sh.ERROR})/\n"
        f'failed to execute command: timeout waiting for "{sh.ERROR}"'
    )
    assert sh.error_in(log) is None
    assert sh.error_in(log + "\nnarratty error: no git") == "no git"


def test_messages_the_recorder_waits_for_start_on_a_cleared_screen() -> None:
    script = sh.need(["no-such-tool"], "x", "here")
    result = subprocess.run(["sh", "-c", script], capture_output=True, text=True, check=False)
    assert result.stderr.startswith("\033[H\033[2J\033[3J")
