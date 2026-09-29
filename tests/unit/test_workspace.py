"""Workspace modes: snapshot, rw and ro."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from narratty.errors import UsageError
from narratty.workspace import dirty_files, export_artifacts, git_root, prepare_workspace, snapshot


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    (root / "app" / "main.py").write_text("print('v1')\n", encoding="utf-8")
    (root / "gone.txt").write_text("bye\n", encoding="utf-8")
    (root / ".gitignore").write_text("build/\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init")
    return root


def test_snapshot_of_a_git_repo_includes_uncommitted_work(repo: Path, tmp_path: Path) -> None:
    (repo / "app" / "main.py").write_text("print('v2')\n", encoding="utf-8")  # modified
    (repo / "new.txt").write_text("new\n", encoding="utf-8")  # untracked
    (repo / "gone.txt").unlink()  # deleted
    (repo / "build").mkdir()
    (repo / "build" / "out.bin").write_text("ignored\n", encoding="utf-8")  # ignored
    dest = tmp_path / "snap"
    dest.mkdir()
    path = snapshot(repo / "app", dest)
    assert path == dest / "repo" / "app", "the path inside the clone matches workspace.source"
    clone = dest / "repo"
    assert (clone / "app" / "main.py").read_text(encoding="utf-8") == "print('v2')\n"
    assert (clone / "new.txt").exists()
    assert not (clone / "gone.txt").exists()
    assert not (clone / "build").exists()
    assert (clone / ".git").is_dir()


def test_snapshot_without_uncommitted_work(repo: Path, tmp_path: Path) -> None:
    (repo / "app" / "main.py").write_text("print('v2')\n", encoding="utf-8")
    dest = tmp_path / "snap"
    dest.mkdir()
    snapshot(repo, dest, include_uncommitted=False)
    assert (dest / "repo" / "app" / "main.py").read_text(encoding="utf-8") == "print('v1')\n"


def test_snapshot_of_a_plain_directory(tmp_path: Path) -> None:
    source = tmp_path / "plain"
    source.mkdir()
    (source / "a.txt").write_text("a", encoding="utf-8")
    dest = tmp_path / "snap"
    dest.mkdir()
    assert (snapshot(source, dest) / "a.txt").read_text(encoding="utf-8") == "a"


def test_snapshot_never_copies_itself(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    scratch = tmp_path / "cache" / "workspaces"
    with prepare_workspace(tmp_path, "snapshot", scratch=scratch) as workspace:
        assert (workspace.path / "a.txt").exists()
        assert not (workspace.path / "cache").exists()


def test_snapshot_is_removed_unless_kept(repo: Path, tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    with prepare_workspace(repo, "snapshot", scratch=scratch) as workspace:
        (workspace.path / "built.txt").write_text("x", encoding="utf-8")
        snapshot_root = workspace.snapshot_root
    assert snapshot_root is not None and not snapshot_root.exists()
    assert not (repo / "built.txt").exists(), "the source is untouched"
    with prepare_workspace(repo, "snapshot", scratch=scratch, keep=True) as workspace:
        kept = workspace.snapshot_root
    assert kept is not None and kept.exists()


def test_rw_refuses_a_dirty_tree(repo: Path, tmp_path: Path) -> None:
    (repo / "app" / "main.py").write_text("print('v2')\n", encoding="utf-8")
    with (
        pytest.raises(UsageError, match="uncommitted changes"),
        prepare_workspace(repo, "rw", scratch=tmp_path),
    ):
        pass
    messages: list[str] = []
    with prepare_workspace(repo, "rw", scratch=tmp_path, allow_dirty=True, log=messages.append) as workspace:
        assert workspace.path == repo.resolve()
    assert messages == [f"the demo changed 1 files in {repo.resolve()}: app/main.py"]


def test_ro_is_in_place_and_warns_natively(repo: Path, tmp_path: Path) -> None:
    messages: list[str] = []
    with prepare_workspace(repo, "ro", scratch=tmp_path, log=messages.append) as workspace:
        assert workspace.path == repo.resolve() and workspace.read_only
    assert any("only enforced in a container" in m for m in messages)


def test_missing_source(tmp_path: Path) -> None:
    with (
        pytest.raises(UsageError, match="does not exist"),
        prepare_workspace(tmp_path / "nope", "rw", scratch=tmp_path),
    ):
        pass


def test_git_helpers(repo: Path, tmp_path: Path) -> None:
    assert git_root(repo / "app") == repo.resolve()
    assert git_root(tmp_path) is None
    assert dirty_files(repo) == []
    (repo / "x.txt").write_text("x", encoding="utf-8")
    assert dirty_files(repo) == ["x.txt"]


def test_export_artifacts(tmp_path: Path) -> None:
    work = tmp_path / "work"
    (work / "dist" / "sub").mkdir(parents=True)
    (work / "dist" / "app.whl").write_text("w", encoding="utf-8")
    (work / "dist" / "sub" / "x.txt").write_text("x", encoding="utf-8")
    (work / "report.html").write_text("r", encoding="utf-8")
    copied = export_artifacts(work, ["dist", "*.html", "missing/*"], tmp_path / "out")
    assert sorted(p.relative_to(tmp_path / "out").as_posix() for p in copied) == ["dist", "report.html"]
    assert (tmp_path / "out" / "dist" / "sub" / "x.txt").exists()
