"""The editor layout helper."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from narratty import editor
from narratty.render.script import encode_path


def test_tmux_argv_builds_both_panes() -> None:
    argv = editor.tmux_argv("zsh", "% ", Path("/conf"), 42, "narratty-1")
    assert argv[:6] == ["tmux", "-L", "narratty-1", "-f", "/conf", "new-session"]
    assert "yazi --client-id 42" in argv
    assert "zsh --no-rcs --no-globalrcs" in argv
    assert "PS1='% '; clear" in argv
    assert argv[-6:] == ["set", "-p", "-t", ":.2", "@title", "Terminal"]
    assert argv.count(";") == 5


def test_reveal_asks_yazi_for_the_path_under_the_root(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setenv(editor.ROOT_ENV, "/work")
    monkeypatch.setenv(editor.YAZI_ID_ENV, "7")
    editor.main(["reveal", encode_path("src/it's.py")])
    assert calls == [["ya", "emit-to", "7", "reveal", "/work/src/it's.py"]]
