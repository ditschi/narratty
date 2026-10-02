"""``build --watch``: rebuild when something the video depends on changes.

Plain polling of modification times, so it needs no extra dependency and works the
same on every platform and over network or container mounts. A change during a build
starts the next build right after it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from narratty.errors import NarrattyError

POLL_S = 0.5
DEBOUNCE_S = 0.3


def watched_files(spec_path: Path) -> list[Path]:
    """The spec and the files it names that a rebuild should react to.

    Those are the project and user lexicon, files under ``cache.inputs`` and local
    pages shown in a browser view. A spec that does not parse yet (it is being edited)
    is watched alone.
    """
    from narratty.build import Plan
    from narratty.config import config_dir
    from narratty.spec import load_spec
    from narratty.spec.model import ShowBrowser
    from narratty.tts.lexicon import USER_FILE, project_file

    files = [spec_path.resolve()]
    try:
        spec = load_spec(spec_path)
    except NarrattyError:
        return files
    source = Plan.source_of(spec_path, spec)
    files += [path for path in (project_file(spec_path), config_dir() / USER_FILE) if path is not None]
    for pattern in spec.cache.inputs:
        files += [path for path in source.glob(pattern) if path.is_file()]
    for scene in spec.scenes:
        for action in scene.actions:
            if isinstance(action, ShowBrowser) and not action.browser.url.startswith(("http://", "https://")):
                files.append(source / action.browser.url)
    return files


def stamp(files: list[Path]) -> dict[Path, float]:
    """Modification time of each existing file (a missing one counts as 0)."""
    stamps = {}
    for path in files:
        try:
            stamps[path] = path.stat().st_mtime
        except OSError:
            stamps[path] = 0.0
    return stamps


def watch(
    spec_path: Path,
    build: Callable[[], None],
    *,
    say: Callable[[str], None],
    sleep: Callable[[float], None] = time.sleep,
    rounds: int | None = None,
) -> None:
    """Run ``build`` now and again after every change to a watched file, until Ctrl+C.

    A failed build is reported and waited out: fix the cause and save. ``rounds`` limits
    the number of builds (for tests).
    """
    done = 0
    while rounds is None or done < rounds:
        before = stamp(watched_files(spec_path))
        try:
            build()
        except NarrattyError as error:
            from narratty.ui import console

            console.print_error(error)
        done += 1
        if rounds is not None and done >= rounds:
            return
        say("watching for changes (Ctrl+C to stop)")
        changed = stamp(watched_files(spec_path)) != before
        while not changed:
            sleep(POLL_S)
            changed = stamp(watched_files(spec_path)) != before
        sleep(DEBOUNCE_S)
        say("change detected")
