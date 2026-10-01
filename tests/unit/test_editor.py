"""The editor layout's commands."""

from __future__ import annotations

import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from narratty import editor


def _fake_bin(tmp_path: Path, **tools: str) -> Path:
    """A directory with ``sh`` and fake tools; each tool's script is its value."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "sh").symlink_to(shutil.which("sh") or "/bin/sh")
    for name, body in tools.items():
        tool = bin_dir / name
        tool.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def _run(command: str, bin_dir: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {"PATH": str(bin_dir), "TMUX": "outer"}
    return subprocess.run(
        ["/bin/sh", "-c", command], cwd=cwd, env=env, capture_output=True, text=True, check=False
    )


def test_start_builds_both_panes(tmp_path: Path) -> None:
    log = tmp_path / "argv"
    record = (
        f'printf "%s\\n" "$@" >{log}; printf "TMUX=%s ROOT=%s\\n" "$TMUX" "$NARRATTY_EDITOR_ROOT" >>{log}'
    )
    bin_dir = _fake_bin(tmp_path, tmux=record, yazi="true", ya="true")
    command = editor.start_command("zsh", "PS1='% '; clear", yazi_id=42)
    result = _run(command, bin_dir, tmp_path)
    assert result.returncode == 0, result.stderr
    argv = log.read_text(encoding="utf-8").splitlines()
    assert argv[:4] == ["-L", "narratty-42", "-f", "/dev/null"]
    assert "yazi --client-id 42" in argv
    assert "zsh --no-rcs --no-globalrcs" in argv
    assert "PS1='% '; clear" in argv
    assert argv.count(";") >= 5 and "start-server" in argv
    assert argv[argv.index("@title") + 1] == "Explorer"
    assert argv[-1] == f"TMUX= ROOT={tmp_path}", "never nested in the caller's tmux, rooted here"


def test_the_terminal_pane_can_run_something_else(tmp_path: Path) -> None:
    log = tmp_path / "argv"
    bin_dir = _fake_bin(tmp_path, tmux=f'printf "%s\\n" "$@" > {log}', yazi="true", ya="true")
    command = editor.start_command("bash", "clear", terminal="docker exec -it env bash")
    assert _run(command, bin_dir, tmp_path).returncode == 0
    assert "docker exec -it env bash" in log.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("missing", ["tmux", "yazi", "ya"])
def test_a_missing_tool_is_named(tmp_path: Path, missing: str) -> None:
    tools = {name: "true" for name in editor.TOOLS if name != missing}
    result = _run(
        editor.start_command("bash", "clear", where="in the project environment"),
        _fake_bin(tmp_path, **tools),
        tmp_path,
    )
    assert result.returncode == 1
    assert f"narratty error: the editor layout needs {missing} in the project environment" in result.stderr


def test_the_start_command_hides_the_pane_titles(tmp_path: Path) -> None:
    command = editor.start_command("bash", "clear")
    assert editor.TERMINAL_TITLE not in command, "the recorder waits for it on screen"


def test_reveal_asks_yazi_for_the_path_under_the_root(tmp_path: Path) -> None:
    log = tmp_path / "ya"
    bin_dir = _fake_bin(tmp_path, ya=f'printf "%s\\n" "$@" > {log}')
    env = {"PATH": str(bin_dir), editor.ROOT_ENV: "/work dir", editor.YAZI_ID_ENV: "7"}
    script = editor.reveal_script("src/it's #1.py")
    subprocess.run(["/bin/sh", "-c", script], env=env, check=True)
    assert log.read_text(encoding="utf-8").splitlines() == [
        "emit-to",
        "7",
        "reveal",
        "/work dir/src/it's #1.py",
    ]
