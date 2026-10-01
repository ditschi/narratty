"""Fast pauses: record long pauses briefly and fill them with still frames.

Most of a narrated video is pauses: the screen holds still while the narration
talks. VHS records in real time, so a 10 s pause costs 10 s of recording. With fast
pauses, a visible pause longer than ``SETTLE_MS`` is recorded for ``SETTLE_MS`` only,
and its last frame is repeated for the rest. That is only right when the screen is
still by then, so the recording is checked: the last ``STILL_MS`` of every shortened
pause must be unchanged, and no command the scene started may still be running (a
silent command would print later; see :func:`running_command`).

To find the pauses in the recording, VHS's progress output (one line per command, as
it starts) is timestamped and mapped to recorded time, and each pause is then matched
to a still stretch of the video.
"""

from __future__ import annotations

import os
import termios
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from narratty.errors import RenderError

SETTLE_MS = 1000
STILL_MS = 500
# How far a pause's estimated end may be off from where it is in the video.
TOLERANCE_MS = 150
_SETTINGS = ("Output", "Set")


@dataclass(frozen=True)
class Pause:
    """A pause recorded as ``SETTLE_MS``.

    ``command`` is its index among the tape's commands, ``scene_command`` that of its
    scene's first command.
    """

    command: int
    planned_ms: int
    scene_id: str | None
    scene_command: int = 0


@dataclass(frozen=True)
class Insert:
    """Repeat video frame ``frame`` ``count`` more times."""

    frame: int
    count: int


def command_keyword(line: str) -> str:
    """``Type@50ms "ls"`` → ``Type``, ``Wait+Screen@1s /x/`` → ``Wait``: the word VHS prints."""
    word = line.split(maxsplit=1)[0]
    return word.split("@")[0].split("+")[0]


def pause_ends_ms(
    commands: Sequence[str], pauses: Sequence[Pause], printed: Sequence[tuple[float, str]], video_ms: int
) -> list[int]:
    """Where each pause ends in the recorded video.

    ``commands`` are the tape's command keywords, ``printed`` VHS's progress lines with
    the time (seconds) each was printed. Hidden stretches are left out, and the result
    is scaled to the video's real length, since VHS's frame rate drifts a little.
    """
    progress = list(printed)
    for index, keyword in enumerate(commands):
        if index >= len(progress) or progress[index][1].split(maxsplit=1)[0] != keyword:
            raise RenderError(
                "could not follow VHS's progress output to find the pauses",
                hint="Build without --fast.",
            )
    starts = [stamp for stamp, _ in progress[: len(commands)]]
    end = progress[len(commands)][0] if len(progress) > len(commands) else starts[-1]
    visible_before: list[float] = []  # recorded seconds before each command starts
    recorded, visible, started = 0.0, False, False
    for index, keyword in enumerate(commands):
        if visible:
            recorded += starts[index] - starts[index - 1]
        visible_before.append(recorded)
        if not started and keyword not in _SETTINGS:
            started, visible = True, keyword != "Hide"  # recording starts after the settings
        elif keyword in ("Hide", "Show"):
            visible = keyword == "Show"
    total = recorded + (end - starts[-1] if visible else 0.0)
    scale = video_ms / (total * 1000) if total else 1.0
    ends = []
    for pause in pauses:
        after = pause.command + 1
        seconds = visible_before[after] if after < len(commands) else total
        ends.append(round(seconds * 1000 * scale))
    return ends


def plan_stills(
    pauses: Sequence[Pause],
    ends_ms: Sequence[int],
    freezes: Sequence[tuple[int, int | None]],
    frame_rate: float,
) -> tuple[list[Insert], list[Pause]]:
    """Frames to repeat for each pause, and the pauses that were not still.

    ``freezes`` are the video's still stretches in milliseconds (end ``None``: until the
    end). A pause counts as still when one stretch covers its last ``STILL_MS``, allowing
    ``TOLERANCE_MS`` for the estimated end.
    """
    inserts: list[Insert] = []
    moving: list[Pause] = []
    for pause, end in zip(pauses, ends_ms, strict=True):
        low, high = end - STILL_MS + TOLERANCE_MS, end - TOLERANCE_MS
        if not any(start <= low and (stop is None or stop >= high) for start, stop in freezes):
            moving.append(pause)
        frame = int((end - STILL_MS / 2) * frame_rate / 1000)
        inserts.append(Insert(frame, round((pause.planned_ms - SETTLE_MS) * frame_rate / 1000)))
    return inserts, moving


def running_command(vhs_pid: int, proc: Path = Path("/proc")) -> int | None:
    """Process group of a command running in the foreground of the recorded shell.

    Only a command that is not reading keys counts: its terminal is in canonical
    (line) mode, as the shell leaves it. Interactive programs (editors, pagers, tmux)
    switch that off. ``None`` when the shell waits at its prompt, an interactive program
    runs, or it cannot be told (no ``/proc``, the shell not found). The shell is the
    child of VHS's ttyd.
    """
    parents: dict[int, int] = {}
    names: dict[int, str] = {}
    stats: dict[int, list[str]] = {}
    for entry in proc.glob("[0-9]*/stat"):
        try:
            text = entry.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        name_end = text.rfind(")")
        fields = text[name_end + 2 :].split()
        pid = int(entry.parent.name)
        names[pid], parents[pid], stats[pid] = text[text.find("(") + 1 : name_end], int(fields[1]), fields
    ttyd = next(
        (pid for pid, name in names.items() if name == "ttyd" and _descends(pid, vhs_pid, parents)), None
    )
    shell = next((pid for pid, parent in parents.items() if parent == ttyd), None)
    if shell is None:
        return None
    # After the name: state, ppid, pgrp, session, tty_nr, tpgid.
    group, foreground = int(stats[shell][2]), int(stats[shell][5])
    if foreground in (group, -1) or not _line_mode(proc / str(shell) / "fd" / "0"):
        return None
    return foreground


def _line_mode(tty: Path) -> bool:
    try:
        fd = os.open(tty, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
    except OSError:
        return False
    try:
        return bool(termios.tcgetattr(fd)[3] & termios.ICANON)
    except termios.error:
        return False
    finally:
        os.close(fd)


def _descends(pid: int, ancestor: int, parents: Mapping[int, int]) -> bool:
    while pid > 1:
        if pid == ancestor:
            return True
        pid = parents.get(pid, 0)
    return False


class JobWatch:
    """Notes the command running in the recorded shell at each scene start and pause end.

    A pause ends busy when a command runs that did not run when its scene started: the
    scene started it and it is still going, however still the screen looks.
    """

    def __init__(
        self, pauses: Sequence[Pause], sample: Callable[[int], int | None] = running_command
    ) -> None:
        self._points = {p.command + 1 for p in pauses} | {p.scene_command for p in pauses}
        self._sample = sample
        self.jobs: dict[int, int | None] = {}

    def __call__(self, index: int, vhs_pid: int) -> None:
        """Progress line ``index`` was printed (the command it names is about to start)."""
        if index in self._points:
            self.jobs[index] = self._sample(vhs_pid)

    def busy(self, pause: Pause) -> bool:
        """Whether a command this pause's scene started was still running at its end."""
        job = self.jobs.get(pause.command + 1)
        return job is not None and job != self.jobs.get(pause.scene_command)
