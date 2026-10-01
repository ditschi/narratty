"""The diff commands, run with a real sh and git."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from narratty import diff

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (project / "README.md").write_text("# App\n", encoding="utf-8")
    return project


@pytest.fixture
def base(tmp_path: Path) -> str:
    return str(tmp_path / "base dir")  # a space: the commands must quote it


def _sh(command: str, cwd: Path, path: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {"PATH": path} if path else None
    return subprocess.run(
        ["/bin/sh", "-c", command], cwd=cwd, capture_output=True, text=True, check=False, env=env
    )


def _start(root: Path, base: str) -> subprocess.CompletedProcess[str]:
    return _sh(diff.start_command(base), root)


def _show(root: Path, base: str, *paths: str) -> str:
    result = _sh(diff.show_script(base, paths), root)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_changes_since_the_baseline(root: Path, base: str) -> None:
    started = _start(root, base)
    assert started.returncode == 0 and diff.READY in started.stderr
    assert _show(root, base) == diff.NO_CHANGES + "\n"
    (root / "src" / "app.py").write_text("print('welcome')\n", encoding="utf-8")
    (root / "NEW.txt").write_text("new\n", encoding="utf-8")
    (root / "src" / "__pycache__").mkdir()
    (root / "src" / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"\0")
    changes = _show(root, base)
    assert "-print('hello')\n+print('welcome')" in changes
    assert "+new" in changes, "new files are included"
    assert "__pycache__" not in changes


def test_changes_can_be_limited_to_paths(root: Path, base: str) -> None:
    _start(root, base)
    (root / "src" / "app.py").write_text("x\n", encoding="utf-8")
    (root / "README.md").write_text("y\n", encoding="utf-8")
    assert "README" not in _show(root, base, "src")
    assert "README" in _show(root, base, "README.md")


def test_paths_with_quotes_and_spaces(root: Path, base: str) -> None:
    name = "it's #1 $x.txt"
    _start(root, base)
    (root / name).write_text("new\n", encoding="utf-8")
    assert "+new" in _show(root, base, name)


def test_changes_are_taken_from_the_recorded_root(root: Path, base: str) -> None:
    _start(root, base)
    (root / "README.md").write_text("changed\n", encoding="utf-8")
    result = _sh(diff.show_script(base), root / "src")
    assert "+changed" in result.stdout


def test_the_workspace_repository_is_untouched(root: Path, base: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    _start(root, base)
    (root / "README.md").write_text("changed\n", encoding="utf-8")
    assert "+changed" in _show(root, base)
    assert (Path(base) / "git" / "objects" / "info" / "alternates").is_file()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True)
    assert status.stdout.splitlines() == ["?? README.md", "?? src/"], "nothing staged in the real index"


def test_a_baseline_inside_the_workspace_is_excluded(root: Path) -> None:
    inside = str(root / ".narratty-base")
    _start(root, inside)
    assert _show(root, inside) == diff.NO_CHANGES + "\n"


def test_start_again_replaces_the_baseline(root: Path, base: str) -> None:
    _start(root, base)
    (root / "README.md").write_text("changed\n", encoding="utf-8")
    _start(root, base)
    assert _show(root, base) == diff.NO_CHANGES + "\n"


def test_waits_for_a_key_in_a_popup(root: Path, base: str) -> None:
    _start(root, base)
    result = subprocess.run(
        ["sh", "-c", diff.show_script(base, wait=True)],
        cwd=root, input="\n", capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert result.returncode == 0 and result.stdout.endswith("\x1b[?25l")


def test_without_git_it_says_so_and_fails(root: Path, base: str, tmp_path: Path) -> None:
    only_sh = tmp_path / "bin"
    only_sh.mkdir()
    (only_sh / "sh").symlink_to(shutil.which("sh") or "/bin/sh")
    result = _sh(diff.start_command(base, "in the project environment"), root, path=str(only_sh))
    assert result.returncode == 1
    assert "narratty error: the diff action needs git in the project environment" in result.stderr
