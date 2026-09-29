"""Entry point maps errors to exit codes."""

from __future__ import annotations

import sys

import pytest

from narratty import __main__
from narratty.errors import ExitCode


def test_missing_dependency_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(sys, "argv", ["narratty", "doctor", "--runtime", "native"])
    with pytest.raises(SystemExit) as exc_info:
        __main__.main()
    assert exc_info.value.code == ExitCode.MISSING_DEPENDENCY
