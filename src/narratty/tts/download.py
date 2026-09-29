"""Download voice and model files with checksum verification."""

from __future__ import annotations

import hashlib
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from narratty.errors import MissingDependencyError
from narratty.tts.catalog import RemoteFile

CHUNK = 1 << 20


def download(file: RemoteFile, dest_dir: Path, *, show_progress: bool = True) -> Path:
    """Fetch ``file`` into ``dest_dir`` atomically and return its path.

    The file is written to a ``.part`` sibling first and renamed only after the
    checksum (when pinned) matches, so an interrupted download never looks installed.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / file.name
    partial = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(file.url, timeout=60) as response, partial.open("wb") as sink:  # noqa: S310
            total = int(response.headers.get("Content-Length") or 0) or None
            with _progress(file.name, total, show_progress) as advance:
                while chunk := response.read(CHUNK):
                    sink.write(chunk)
                    digest.update(chunk)
                    advance(len(chunk))
    except (urllib.error.URLError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise MissingDependencyError(
            f"could not download {file.name} from {file.url}: {exc}",
            hint="Check your network connection, or copy the file into the data directory by hand.",
        ) from exc
    if file.sha256 is not None and digest.hexdigest() != file.sha256:
        partial.unlink(missing_ok=True)
        raise MissingDependencyError(
            f"checksum mismatch for {file.name}: expected {file.sha256}, got {digest.hexdigest()}",
            hint="The download was corrupted or the upstream file changed; try again.",
        )
    os.replace(partial, target)
    return target


class _progress:  # noqa: N801 - used like a function
    """Context manager yielding an ``advance(n)`` callback backed by a Rich progress bar."""

    def __init__(self, name: str, total: int | None, enabled: bool) -> None:
        from rich.progress import DownloadColumn, Progress, TransferSpeedColumn

        from narratty.ui.console import err

        self._progress = Progress(
            *Progress.get_default_columns(),
            DownloadColumn(),
            TransferSpeedColumn(),
            console=err,
            disable=not enabled,
            transient=True,
        )
        self._task = self._progress.add_task(f"downloading {name}", total=total)

    def __enter__(self) -> Callable[[int], None]:
        self._progress.start()
        return self._advance

    def _advance(self, amount: int) -> None:
        self._progress.advance(self._task, amount)

    def __exit__(self, *_: object) -> None:
        self._progress.stop()
