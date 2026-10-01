"""The diff helper, with real git."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from narratty import diff

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(diff.BASE_ENV, str(tmp_path / "base"))
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (project / "README.md").write_text("# App\n", encoding="utf-8")
    return project


def test_changes_since_the_baseline(root: Path) -> None:
    diff.start(root)
    assert diff.changes(root) == ""
    (root / "src" / "app.py").write_text("print('welcome')\n", encoding="utf-8")
    (root / "NEW.txt").write_text("new\n", encoding="utf-8")
    (root / "src" / "__pycache__").mkdir()
    (root / "src" / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"\0")
    changes = diff.changes(root)
    assert "-print('hello')\n+print('welcome')" in changes
    assert "+new" in changes, "new files are included"
    assert "__pycache__" not in changes


def test_changes_can_be_limited_to_paths(root: Path) -> None:
    diff.start(root)
    (root / "src" / "app.py").write_text("x\n", encoding="utf-8")
    (root / "README.md").write_text("y\n", encoding="utf-8")
    assert "README" not in diff.changes(root, ["src"])
    assert "README" in diff.changes(root, ["README.md"])


def test_changes_use_the_recorded_root(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    diff.start(root)
    (root / "README.md").write_text("changed\n", encoding="utf-8")
    monkeypatch.chdir(root / "src")
    assert "+changed" in diff.changes(root / "src")


def test_the_workspace_repository_is_untouched(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    diff.start(root)
    (root / "README.md").write_text("changed\n", encoding="utf-8")
    assert "+changed" in diff.changes(root)
    assert (diff.base_dir(root) / "git" / "objects" / "info" / "alternates").is_file()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True)
    assert status.stdout.splitlines() == ["?? README.md", "?? src/"], "nothing staged in the real index"


def test_base_dir_without_the_environment(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(diff.BASE_ENV)
    assert diff.base_dir(root) == diff.base_dir(root)
    assert diff.base_dir(root) != diff.base_dir(root / "src")


def test_pretty_falls_back_to_plain_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    assert diff.pretty("+x\n") == "+x\n"


def test_main_prints_no_changes(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(root)
    diff.main(["start"])
    assert diff.READY in capsys.readouterr().err
    diff.main(["show"])
    assert capsys.readouterr().out == diff.NO_CHANGES + "\n"
