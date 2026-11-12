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


def test_errors_print_image_tags_literally(capsys: pytest.CaptureFixture[str]) -> None:
    from narratty.errors import NarrattyError
    from narratty.ui.console import print_error

    print_error(NarrattyError("could not pull img:x: denied", hint="use img:latest:"))
    err = capsys.readouterr().err
    assert "img:x: denied" in err and "img:latest:" in err, "`:x:` is not an emoji code"
