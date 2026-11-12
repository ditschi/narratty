"""How long each ``run`` command really takes, measured by ``narratty check``.

The plan counts a ``run`` as its typing plus ``timing.run_hold_ms``; it cannot know
that ``make`` takes twelve seconds. ``check`` runs every command anyway, so it notes
how long each one ran (from its Enter until the shell had the terminal back) and keeps
that in the cache directory. ``plan``, ``tape`` and ``build`` then wait that long
after the command (see :func:`narratty.timeline.run_holds`), so its output is complete
before the scene goes on and the plan shows realistic lengths.

Entries are keyed by the spec's title, the shell, the layout, the scene id and the
command, so editing a command forgets its measurement. Commands stopped with a
control key (``C-c``) and commands still running when the recording ended are not
recorded. ``timing.measured_durations: false`` ignores the measurements.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from narratty.spec.model import Run, Spec

FILE = "command-durations.json"
FORMAT = 1
# Measurements are rounded up to this, so tiny differences do not change the tape.
STEP_MS = 100

Location = tuple[str, int]  # (scene id, action index)


def _runs(spec: Spec) -> list[tuple[Location, str]]:
    """Every ``run`` action, where it is and the command it runs."""
    return [
        ((scene.id, index), action.run)
        for scene in spec.scenes
        for index, action in enumerate(scene.actions)
        if isinstance(action, Run)
    ]


def command_key(spec: Spec, scene_id: str, command: str) -> str:
    """Key of one command's measurement."""
    terminal = spec.terminal
    parts = [FORMAT, spec.meta.title, terminal.shell, terminal.layout, scene_id, command]
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:32]


def match_runs(spec: Spec, took: Sequence[tuple[str, int | None]]) -> dict[Location, int]:
    """How long each ``run`` of ``spec`` took, from the submitted lines of a recording.

    ``took`` holds each line submitted with Enter, in order, and how long its command
    ran. A ``run`` is the next submitted line equal to its command's last line.
    """
    found: dict[Location, int] = {}
    position = 0
    for location, command in _runs(spec):
        last = command.split("\n")[-1].strip()
        for index in range(position, len(took)):
            line, ms = took[index]
            if line == last:
                if ms is not None:
                    found[location] = ms
                position = index + 1
                break
    return found


def _rounded(ms: int) -> int:
    return math.ceil(ms / STEP_MS) * STEP_MS


class DurationStore:
    """The measurements, one JSON file in the cache directory."""

    def __init__(self, root: Path) -> None:
        self.path = root / FILE

    def _entries(self) -> dict[str, dict[str, object]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def lookup(self, spec: Spec) -> dict[Location, int]:
        """The measured duration of each ``run`` of ``spec`` that has one."""
        entries = self._entries()
        found: dict[Location, int] = {}
        for location, command in _runs(spec):
            entry = entries.get(command_key(spec, location[0], command))
            if isinstance(entry, dict) and isinstance(entry.get("ms"), int):
                found[location] = int(entry["ms"])  # type: ignore[call-overload]
        return found

    def record(self, spec: Spec, measured: Mapping[Location, int]) -> None:
        """Add or replace the measurements of ``spec``'s commands."""
        commands = dict(_runs(spec))
        entries = self._entries()
        now = int(time.time())
        for location, ms in measured.items():
            scene_id, _ = location
            key = command_key(spec, scene_id, commands[location])
            entries[key] = {"ms": _rounded(ms), "scene": scene_id, "command": commands[location], "at": now}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".durations-")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(entries, handle, indent=1, sort_keys=True)
        os.replace(tmp, self.path)


def describe(spec: Spec, measured: Mapping[Location, int]) -> str:
    """``scene (12.3s), scene (4.1s)`` for the commands that outlast ``run_hold_ms``."""
    slow = [(loc, ms) for loc, ms in measured.items() if ms > spec.timing.run_hold_ms]
    return ", ".join(f"{scene_id} ({ms / 1000:.1f}s)" for (scene_id, _), ms in slow)


def load(spec: Spec, root: Path, log: Callable[[str], None] | None = None) -> dict[Location, int]:
    """The measurements to plan ``spec`` with (none when the spec turns them off)."""
    if not spec.timing.measured_durations:
        return {}
    measured = DurationStore(root).lookup(spec)
    if log and (slow := describe(spec, measured)):
        log(f"waiting for commands as long as `narratty check` measured them: {slow}")
    return measured
