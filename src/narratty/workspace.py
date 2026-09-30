"""Prepare the directory a demo runs in, according to ``workspace.mode``.

- ``snapshot`` (default): a throwaway copy. For git repositories a local clone of
  HEAD plus your uncommitted and untracked (not ignored) files, so builds can write
  into the tree without touching your checkout.
- ``rw``: the real directory. Refused when it has uncommitted changes, unless
  ``--allow-dirty``, because a demo build could overwrite them.
- ``ro``: the real directory, mounted read-only in the container (not enforceable
  in native mode).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from narratty.errors import NarrattyError, UsageError

Log = Callable[[str], None]
MODES = ("snapshot", "rw", "ro")


@dataclass(frozen=True)
class PreparedWorkspace:
    """The directory to run in, and how it relates to the source."""

    path: Path
    mode: str
    source: Path
    snapshot_root: Path | None = None

    @property
    def read_only(self) -> bool:
        """True when the container should mount the workspace read-only."""
        return self.mode == "ro"


def _git(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)  # noqa: S603, S607


def git_root(path: Path) -> Path | None:
    """Top level of the git work tree containing ``path``, if any."""
    if shutil.which("git") is None:
        return None
    result = _git(["rev-parse", "--show-toplevel"], path)
    return Path(result.stdout.decode().strip()) if result.returncode == 0 else None


def _split(output: bytes) -> list[str]:
    return [item for item in output.decode("utf-8", "surrogateescape").split("\0") if item]


def dirty_files(root: Path) -> list[str]:
    """Tracked files that differ from HEAD plus untracked, non-ignored files."""
    changed = _git(["diff", "--name-only", "-z", "HEAD"], root)
    untracked = _git(["ls-files", "--others", "--exclude-standard", "-z"], root)
    return sorted(set(_split(changed.stdout)) | set(_split(untracked.stdout)))


def _check(result: subprocess.CompletedProcess[bytes], what: str) -> None:
    if result.returncode != 0:
        raise NarrattyError(f"{what} failed: {result.stderr.decode(errors='replace').strip()}")


def _skip(dest: Path) -> Callable[[str, list[str]], set[str]]:
    """copytree ignore callback that never copies the snapshot area into itself."""
    dest = dest.resolve()

    def ignore(directory: str, names: list[str]) -> set[str]:
        skipped = {".git"} if Path(directory) == dest else set()
        for name in names:
            path = (Path(directory) / name).resolve()
            if path == dest or dest.is_relative_to(path):
                skipped.add(name)
        return skipped

    return ignore


def snapshot(source: Path, dest: Path, *, include_uncommitted: bool = True) -> Path:
    """Copy ``source`` into ``dest``; returns the path corresponding to ``source``."""
    root = git_root(source)
    if root is None:
        target = dest / source.name
        shutil.copytree(source, target, symlinks=True, ignore=_skip(dest))
        return target
    clone = dest / root.name
    head = _git(["rev-parse", "HEAD"], root)
    if head.returncode != 0:  # a repository without commits: copy the files instead
        skip = _skip(dest)
        shutil.copytree(
            root, clone, symlinks=True, ignore=lambda d, names: skip(d, names) | ({".git"} & set(names))
        )
        return clone / source.relative_to(root)
    _check(_git(["clone", "--quiet", "--local", "--no-checkout", str(root), str(clone)], dest), "git clone")
    _check(_git(["checkout", "--quiet", "--detach", head.stdout.decode().strip()], clone), "git checkout")
    if include_uncommitted:
        for name in dirty_files(root):
            original, copy = root / name, clone / name
            if original.is_symlink() or original.is_file():
                copy.parent.mkdir(parents=True, exist_ok=True)
                copy.unlink(missing_ok=True)
                shutil.copy2(original, copy, follow_symlinks=False)
            elif not original.exists():
                copy.unlink(missing_ok=True)
    return clone / source.relative_to(root)


@contextmanager
def prepare_workspace(
    source: Path,
    mode: str,
    *,
    scratch: Path,
    include_uncommitted: bool = True,
    allow_dirty: bool = False,
    keep: bool = False,
    in_container: bool = False,
    log: Log | None = None,
) -> Iterator[PreparedWorkspace]:
    """Yield the workspace for ``mode``; a snapshot is removed afterwards unless ``keep``."""
    say = log or (lambda _message: None)
    source = source.resolve()
    if not source.is_dir():
        raise UsageError(f"workspace {source} does not exist", hint="Check `workspace.source` in the spec.")
    if mode == "rw" and not allow_dirty:
        root = git_root(source)
        if root is not None and dirty_files(root):
            raise UsageError(
                f"{root} has uncommitted changes and workspace.mode is rw",
                hint="Commit or stash them, pass --allow-dirty, or use --workspace-mode snapshot.",
            )
    if mode == "ro" and not in_container:
        say("workspace.mode ro is only enforced in a container; running natively in place")
    if mode != "snapshot":
        yield PreparedWorkspace(source, mode, source)
        if mode == "rw" and (root := git_root(source)) is not None and (changed := dirty_files(root)):
            say(f"the demo changed {len(changed)} files in {root}: {', '.join(changed[:10])}")
        return
    root = scratch / f"{source.name}-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    root.mkdir(parents=True)
    say(f"snapshotting {source}")
    try:
        path = snapshot(source, root, include_uncommitted=include_uncommitted)
        yield PreparedWorkspace(path, mode, source, root)
    finally:
        if keep:
            say(f"kept the workspace snapshot at {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)


def export_artifacts(workspace: Path, patterns: Sequence[str], dest: Path) -> list[Path]:
    """Copy files matching ``patterns`` (globs relative to the workspace) into ``dest``."""
    copied: list[Path] = []
    for pattern in patterns:
        for match in sorted(workspace.glob(pattern)):
            target = dest / match.relative_to(workspace)
            target.parent.mkdir(parents=True, exist_ok=True)
            if match.is_dir():
                shutil.copytree(match, target, symlinks=True, dirs_exist_ok=True)
            else:
                shutil.copy2(match, target, follow_symlinks=False)
            copied.append(target)
    return copied
