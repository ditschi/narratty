"""Record the script as an asciicast (v2) by running the shell in a pseudo-terminal.

VHS cannot write asciicasts, so this recorder plays the same script itself: it types
into a real shell, records what the shell prints, and stamps every event with a
clock that stops while recording is hidden. Hidden output is kept (at the moment
recording resumes), so the screen looks the same as in the video.
"""

from __future__ import annotations

import codecs
import contextlib
import fcntl
import json
import os
import re
import select
import signal
import struct
import subprocess
import termios
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from narratty.errors import RenderError
from narratty.render.pauses import SETTLE_MS, STILL_MS
from narratty.render.script import (
    Ctrl,
    Cue,
    Hide,
    Mark,
    Press,
    Show,
    Sleep,
    Step,
    TimelapseEnd,
    Type,
    WaitScreen,
)
from narratty.render.shell_hooks import SHELL_ARGV
from narratty.spec.model import Terminal
from narratty.timeline import timelapse_layout

if TYPE_CHECKING:
    from narratty.render.outputs import Submitted

# VHS's defaults: 60 px padding; a monospace cell is about 0.6 × 1.2 font sizes.
_PADDING_PX = 60
CELL_WIDTH, _CELL_HEIGHT = 0.6, 1.2


KEYS = {
    "Backspace": "\x7f",
    "Delete": "\x1b[3~",
    "Down": "\x1b[B",
    "Enter": "\r",
    "Escape": "\x1b",
    "Insert": "\x1b[2~",
    "Left": "\x1b[D",
    "PageDown": "\x1b[6~",
    "PageUp": "\x1b[5~",
    "Right": "\x1b[C",
    "Space": " ",
    "Tab": "\t",
    "Up": "\x1b[A",
}


def terminal_size(term: Terminal) -> tuple[int, int]:
    """Columns and rows matching the video's pixel size and font size."""
    cols = (term.width - 2 * _PADDING_PX) / (term.font_size * CELL_WIDTH)
    rows = (term.height - 2 * _PADDING_PX) / (term.font_size * _CELL_HEIGHT)
    return max(20, int(cols)), max(5, int(rows))


def ctrl_char(char: str) -> str:
    """The control character Ctrl+``char`` sends (``C`` → ``\\x03``)."""
    return chr(ord(char.upper()) & 0x1F)


# How often a pause checks whether a running command has finished.
_POLL = 0.1

_CLEAR = re.compile(r"\x1b\[2J|\x1bc")
ESCAPE = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]|\x1b[()*+].|\x1b[@-Z\\-_]|\x1b."
)


@dataclass
class ScreenText:
    """The printed text since the last clear, without escape sequences.

    Close enough to the screen for ``wait`` patterns on command output; cursor
    movement inside full-screen programs is not modelled.
    """

    rows: int
    lines: list[str] = field(default_factory=lambda: [""])

    def feed(self, data: str) -> None:
        """Add printed output."""
        cleared = list(_CLEAR.finditer(data))
        if cleared:
            self.lines = [""]
            data = data[cleared[-1].end() :]
        for char in ESCAPE.sub("", data):
            if char == "\n":
                self.lines.append("")
            elif char == "\r":
                continue  # the \n of \r\n moves on; a lone \r redraws the line in place
            elif char == "\b":
                self.lines[-1] = self.lines[-1][:-1]
            elif char >= " " or char == "\t":
                self.lines[-1] += char
        del self.lines[: -self.rows]

    @property
    def text(self) -> str:
        """The visible lines."""
        return "\n".join(self.lines)


class Recorder:
    """A shell in a pseudo-terminal whose output is recorded as asciicast events."""

    def __init__(
        self,
        argv: Sequence[str],
        *,
        cols: int,
        rows: int,
        cwd: Path,
        env: Mapping[str, str],
        clock: Callable[[], float] = time.monotonic,
        fast: bool = False,
        prompt: str = "$ ",
    ) -> None:
        self.cols, self.rows = cols, rows
        self.prompt = prompt.rstrip()
        self.fast = fast
        self._scene_fast = fast  # the current scene's own choice wins
        self.events: list[tuple[float, str, str]] = []
        self.marks: dict[str, float] = {}
        self.cues: dict[str, float] = {}
        self.screen = ScreenText(rows)
        self._clock = clock
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._hidden_total = 0.0
        self._hidden_since: float | None = None
        self._skipped = 0.0  # recorded time saved by timelapse scenes so far
        self._fast: tuple[float, float] | None = None  # (shown seconds at its start, factor)
        self.narration_offsets: dict[str, float] = {}
        self._paused = 0.0  # pause time not waited out (``fast``), still counted as shown
        self._last_output = 0.0
        self.raw: list[str] = []  # all output, for checking what commands printed
        self._raw_length = 0
        self._typed = ""
        self.enters: list[tuple[str, int]] = []  # (typed line, raw offset) at each Enter
        self.prompts: list[int] = []  # raw offsets where the prompt was back
        self.scene: str | None = None  # the scene being played, hidden ones too
        self._entered = 0  # the output chunk at the last Enter
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        try:
            self._proc = subprocess.Popen(  # noqa: S603
                list(argv),
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=cwd,
                env=dict(env),
                start_new_session=True,
                preexec_fn=_take_terminal,  # noqa: PLW1509  # no threads run at this point
            )
        except OSError as error:
            os.close(master)
            raise RenderError(f"could not start {argv[0]}: {error}") from error
        finally:
            os.close(slave)
        self._fd = master
        self._start = clock()

    # ── clock ────────────────────────────────────────────────────────────────

    def _shown(self) -> float:
        current = self._hidden_since if self._hidden_since is not None else self._clock()
        return current - self._start - self._hidden_total + self._paused

    def now(self) -> float:
        """Seconds of recorded time so far (hidden time does not count, timelapse time less)."""
        shown = self._shown()
        if self._fast is None:
            return shown - self._skipped
        start, factor = self._fast
        return start - self._skipped + (shown - start) / factor

    def speed_up(self, factor: float) -> None:
        """Let recorded time run ``factor`` times faster than real time."""
        self._fast = (self._shown(), factor)

    def normal_speed(self) -> None:
        """Back to real time."""
        if self._fast is not None:
            start, factor = self._fast
            self._skipped += (self._shown() - start) * (1 - 1 / factor)
            self._fast = None

    def hide(self) -> None:
        """Stop the recording clock; output keeps being recorded, at this moment."""
        if self._hidden_since is None:
            self._hidden_since = self._clock()

    def show(self) -> None:
        """Restart the recording clock."""
        if self._hidden_since is not None:
            self._hidden_total += self._clock() - self._hidden_since
            self._hidden_since = None

    # ── input and output ─────────────────────────────────────────────────────

    def send(self, text: str) -> None:
        """Write keystrokes to the shell."""
        os.write(self._fd, text.encode())

    def pump(self, seconds: float, until: Callable[[], bool] | None = None) -> bool:
        """Record output for ``seconds``, or until ``until()`` holds (then True)."""
        deadline = self._clock() + seconds
        while True:
            if until is not None and until():
                return True
            remaining = deadline - self._clock()
            if remaining <= 0:
                return False
            ready, _, _ = select.select([self._fd], [], [], remaining)
            if ready and not self._read():
                time.sleep(remaining)  # the shell is gone; let the time pass
                return until() if until is not None else False

    def _read(self) -> bool:
        try:
            data = os.read(self._fd, 65536)
        except OSError:
            data = b""
        if not data:
            return False
        self._last_output = self._clock()
        text = self._decoder.decode(data)
        if text:
            self._output(text)
            self.screen.feed(text)
            self.raw.append(text)
            self._raw_length += len(text)
        return True

    def _output(self, text: str) -> None:
        now = self.now()
        if self.events and self.events[-1][:2] == (now, "o"):  # hidden output: one event
            text = self.events.pop()[2] + text
        self.events.append((now, "o", text))

    def mark(self, label: str) -> None:
        """Remember when ``label`` started and add a marker (a chapter in the player)."""
        self.marks[label] = self.now()
        self.events.append((self.now(), "m", label))

    def close(self) -> float:
        """Stop the shell; returns the recorded length in seconds."""
        self.pump(0)
        end = self.now()
        with contextlib.suppress(ProcessLookupError):
            os.killpg(self._proc.pid, signal.SIGHUP)
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(self._proc.pid, signal.SIGKILL)
            self._proc.wait()
        os.close(self._fd)
        return end

    # ── script ───────────────────────────────────────────────────────────────

    def run(self, step: Step) -> None:
        """Perform one script step."""
        match step:
            case Type(text, speed):
                self._typed += text
                self._keys(list(text), speed)
            case Press(key, speed, count):
                self._press(key, speed, count or 1)
            case Ctrl(char):
                self._typed = ""
                self._keys([ctrl_char(char)], 0)
            case Sleep(ms) if self._may_skip(ms):
                self._pause(ms / 1000)
            case Sleep(ms):
                self.pump(ms / 1000)
            case WaitScreen(pattern, timeout_ms, line, fail):
                self._wait(pattern, timeout_ms, line=line, fail=fail)
            case Hide():
                self.hide()
            case Show():
                self.show()
            case Mark() | TimelapseEnd() | Cue():
                self._section(step)

    def _section(self, step: Mark | TimelapseEnd | Cue) -> None:
        """Scene starts, timelapse ends and cues: remember when they happened."""
        match step:
            case Mark(scene_id, hidden, timelapse, fast):
                self.scene = scene_id
                self._scene_fast = self.fast if fast is None else fast
                if scene_id is not None and not hidden:
                    self._start_scene(scene_id, timelapse)
            case TimelapseEnd():
                self._end_timelapse(step)
            case Cue(label):
                self.cues[label] = self.now()

    def _start_scene(self, scene_id: str, timelapse: float | None) -> None:
        self.mark(scene_id)
        if timelapse:
            self.speed_up(timelapse)

    def _end_timelapse(self, end: TimelapseEnd) -> None:
        """Back to real time; hold the last frame until the scene's narration is done."""
        self.normal_speed()
        sped_ms = round((self.now() - self.marks[end.scene_id]) * 1000)
        offset, freeze = timelapse_layout(sped_ms, end.hold_ms, narration_after=end.narration_after)
        self.narration_offsets[end.scene_id] = offset / 1000
        self.pump(freeze / 1000)

    def _may_skip(self, ms: int) -> bool:
        """Whether a pause may end early: fast (here), shown, long, outside timelapse scenes."""
        return self._scene_fast and self._hidden_since is None and self._fast is None and ms > SETTLE_MS

    def _pause(self, seconds: float) -> None:
        """Pause, but skip the rest once the screen is still.

        Still means: no output for ``STILL_MS`` and no command running (see
        :meth:`running_command`).
        """
        start = self._clock()
        end, still = start + seconds, STILL_MS / 1000
        while True:
            now = self._clock()
            ready = max(self._last_output, start) + still
            if ready <= now and not self.running_command():
                self._paused += end - now
                return
            wake = max(ready, now + _POLL)
            if wake >= end:
                self.pump(end - now)
                return
            self.pump(wake - now)

    def running_command(self) -> bool:
        """Whether a command runs in the foreground that does not read keys.

        Such a command leaves the terminal in canonical (line) mode, as the shell
        does; interactive programs (editors, pagers, tmux) switch that off and count
        as idle.
        """
        try:
            group = os.tcgetpgrp(self._fd)
            canonical = termios.tcgetattr(self._fd)[3] & termios.ICANON
        except (OSError, termios.error):
            return False
        return group != self._proc.pid and bool(canonical)

    def _keys(self, keys: Sequence[str], speed_ms: int) -> None:
        for key in keys:
            self.send(key)
            self.pump(speed_ms / 1000)

    def _press(self, key: str, speed_ms: int, count: int) -> None:
        """Press ``key``; for Enter, note the line it submits and where its output starts."""
        if key != "Enter":
            self._keys([KEYS[key]] * count, speed_ms)
            return
        for _ in range(count):
            self.enters.append((self._typed.strip(), self._raw_length))
            self._entered = len(self.raw)
            self._typed = ""
            self._keys([KEYS[key]], speed_ms)

    def _wait(self, pattern: str, timeout_ms: int, *, line: bool = False, fail: str | None = None) -> None:
        regex, failed = re.compile(pattern), re.compile(fail) if fail else None

        def matches() -> bool:
            text = self.screen.lines[-1] if line else self.screen.text
            if regex.search(text) or (failed and failed.search(text)):
                return True
            return line and self._prompt_was_back()

        found = self.pump(timeout_ms / 1000, matches)
        if found and line:
            self.prompts.append(self._raw_length)
        if failed and (error := failed.search(self.screen.text)) and not regex.search(self.screen.text):
            raise RenderError(error.group(1).strip(), scene=self.scene)
        if not found:
            raise wait_timeout(timeout_ms, None if line else pattern, self.scene)

    def _prompt_was_back(self) -> bool:
        """Whether a line printed since the last Enter started with the prompt and the
        shell is idle: a background job printed after it, so it is no longer last."""
        if not self.prompt or self.running_command():
            return False
        text = ESCAPE.sub("", "".join(self.raw[self._entered :]))
        rows = [
            row.removesuffix("\r").rsplit("\r", 1)[-1] for row in text.split("\n")[1:-1]
        ]  # not the typed line, not the last
        return any(row.startswith(self.prompt) for row in rows)


def wait_timeout(timeout_ms: int, pattern: str | None, scene: str | None) -> RenderError:
    """The error for a ``wait`` that timed out; ``pattern`` None: it waited for the prompt."""
    where = f" in scene {scene!r}" if scene else ""
    if pattern is None:
        return RenderError(
            f"timed out after {timeout_ms} ms{where} waiting for the prompt to come back",
            hint="The command may still run (a server, a pager, a question for input): stop it "
            "with `C-c`, send it to the background with its output redirected, or raise "
            "wait.timeout_ms. Late output from a background job hides the prompt: redirect it "
            "(`server > server.log &`).",
            scene=scene,
        )
    return RenderError(
        f"timed out after {timeout_ms} ms{where} waiting for the screen to match /{pattern}/",
        hint="Check the pattern against the command's output, or raise wait.timeout_ms.",
        scene=scene,
    )


def _take_terminal() -> None:
    """Make the pseudo-terminal the child's controlling terminal (for job control)."""
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


@dataclass(frozen=True)
class Recording:
    """An asciicast, when each visible scene started in it and when each cue was reached."""

    cast: str
    duration_ms: int
    scene_starts_ms: dict[str, int]
    narration_offsets_ms: dict[str, int] = field(default_factory=dict)  # timelapse scenes
    cues_ms: dict[str, int] = field(default_factory=dict)
    submitted: tuple[Submitted, ...] = ()
    """Each line typed at the prompt and what it printed (see ``narratty.render.outputs``)."""


def record(
    steps: Sequence[Step],
    *,
    terminal: Terminal,
    cwd: Path,
    env: Mapping[str, str],
    title: str,
    fast: bool = False,
    shell: str | None = None,
) -> Recording:
    """Run ``steps`` in ``shell`` (default: ``terminal.shell``) inside ``cwd``; returns the asciicast.

    ``fast`` skips the rest of a pause longer than ``SETTLE_MS`` once the output has been
    quiet for ``STILL_MS``; the recording's clock moves on as if it had waited.
    """
    from narratty.render.outputs import captured

    cols, rows = terminal_size(terminal)
    shell_env = {**env, "TERM": "xterm-256color", "COLUMNS": str(cols), "LINES": str(rows)}
    recorder = Recorder(
        SHELL_ARGV[shell or terminal.shell],
        cols=cols,
        rows=rows,
        cwd=cwd,
        env=shell_env,
        fast=fast,
        prompt=terminal.prompt,
    )
    try:
        for step in steps:
            recorder.run(step)
    finally:
        duration = recorder.close()
    header = {
        "version": 2,
        "width": cols,
        "height": rows,
        "title": title,
        "env": {"TERM": "xterm-256color", "SHELL": terminal.shell},
    }
    events = [*recorder.events, (duration, "o", "")]  # the last event sets the length
    lines = [json.dumps(header), *(json.dumps([round(t, 6), kind, data]) for t, kind, data in events)]
    submitted = captured("".join(recorder.raw), recorder.enters, recorder.prompts)
    return Recording(
        "\n".join(lines) + "\n",
        round(duration * 1000),
        {label: round(start * 1000) for label, start in recorder.marks.items()},
        {label: round(offset * 1000) for label, offset in recorder.narration_offsets.items()},
        {label: round(at * 1000) for label, at in recorder.cues.items()},
        tuple(submitted),
    )
