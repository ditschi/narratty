"""Fast pauses: shortening the tape, finding the pauses in the video, planning the stills."""

from __future__ import annotations

import os
import tty
from pathlib import Path

import pytest

from narratty.errors import RenderError
from narratty.render.pauses import (
    SETTLE_MS,
    Insert,
    JobWatch,
    Pause,
    command_keyword,
    pause_ends_ms,
    plan_stills,
    running_command,
)
from narratty.render.tape import build_tape
from narratty.spec.loader import parse_spec
from narratty.timeline import build_timeline

SPEC = """\
timing: {lead_in_ms: 300, tail_ms: 2000, narration_buffer_ms: 0}
end_card: false
scenes:
  - id: setup
    hidden: true
    actions: [{type_command: "cd /srv"}, enter, {hold: 5000}]
  - id: intro
    narration: Hello.
    actions: [{type_command: ls}, enter, {hold: auto}, {hold: 800}]
"""


def _tape(fast: bool) -> tuple[str, tuple[str, ...], tuple[Pause, ...]]:
    spec = parse_spec(SPEC, Path("t.narratty.yaml"))
    tape = build_tape(spec, build_timeline(spec, {"intro": 4000}), Path("/out/v.mp4"), fast=fast)
    return tape.text, tape.commands, tape.pauses


@pytest.mark.parametrize(
    ("line", "keyword"),
    [('Type@40ms "ls"', "Type"), ("Wait+Screen@3000ms /x/", "Wait"), ("Ctrl+C", "Ctrl"), ("Hide", "Hide")],
)
def test_command_keyword_is_what_vhs_prints(line: str, keyword: str) -> None:
    assert command_keyword(line) == keyword


def test_slow_tape_is_unchanged() -> None:
    text, _, pauses = _tape(fast=False)
    assert pauses == ()
    assert "CursorBlink" not in text


def test_fast_tape_shortens_visible_pauses_only() -> None:
    slow, _, _ = _tape(fast=False)
    text, commands, pauses = _tape(fast=True)
    assert "Set CursorBlink false" in text, "a repeated frame must not stop a blinking cursor"
    assert "Sleep 5000ms" in text, "hidden pauses cost no video time and stay"
    assert "Sleep 800ms" in text, "short pauses stay"
    assert "Sleep 300ms" in text
    long_sleeps = [
        line for line in slow.splitlines() if line.startswith("Sleep") and int(line[6:-2]) > SETTLE_MS
    ]
    planned = sorted(int(line[6:-2]) for line in long_sleeps if line != "Sleep 5000ms")
    assert sorted(p.planned_ms for p in pauses) == planned
    assert [p.scene_id for p in pauses] == ["intro", "intro"], "the tail belongs to the last scene"
    lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert len(lines) == len(commands)
    for pause in pauses:
        assert lines[pause.command] == f"Sleep {SETTLE_MS}ms"
        assert lines[pause.scene_command] == 'Type@40ms "ls"'


def _printed(commands: tuple[str, ...], stamps: list[float]) -> list[tuple[float, str]]:
    return [(stamp, f"{keyword} x") for stamp, keyword in zip(stamps, commands, strict=False)]


def test_pause_ends_skip_hidden_time_and_scale_to_the_video() -> None:
    commands = (
        "Output",
        "Set",
        "Hide",
        "Type",
        "Show",
        "Type",
        "Sleep",
        "Type",
        "Hide",
        "Sleep",
        "Show",
        "Sleep",
    )
    stamps = [0.0, 0.1, 0.2, 0.3, 5.0, 5.0, 6.0, 7.0, 8.0, 8.5, 20.0, 21.0]
    printed = [*_printed(commands, stamps), (22.0, "Creating v.mp4...")]
    pauses = [Pause(6, 3000, "a"), Pause(11, 2000, None)]
    # Visible: 5.0 → 8.0 (3 s) and 20.0 → 22.0 (2 s); the video is 10 % longer.
    assert pause_ends_ms(commands, pauses, printed, 5500) == [2200, 5500]


def test_pause_ends_need_vhs_to_print_the_tape_commands() -> None:
    with pytest.raises(RenderError, match="progress"):
        pause_ends_ms(("Hide", "Type"), [], [(0.0, "Hide"), (0.1, "Sleep 1s")], 1000)


def test_plan_stills_repeats_a_frame_of_each_still_pause() -> None:
    pauses = [Pause(5, 4000, "a"), Pause(9, 3000, "b")]
    freezes = [(500, 2000), (2600, 4100), (6000, None)]
    inserts, moving = plan_stills(pauses, [2000, 7000], freezes, 25.0)
    assert moving == []
    assert inserts == [Insert(43, 75), Insert(168, 50)]


def test_plan_stills_reports_pauses_that_kept_changing() -> None:
    pauses = [Pause(5, 4000, "a")]
    inserts, moving = plan_stills(pauses, [2000], [(1800, 3000)], 25.0)
    assert moving == pauses
    assert len(inserts) == 1, "a draft fills it anyway"


def test_job_watch_only_flags_commands_the_scene_started() -> None:
    pauses = [Pause(5, 4000, "a", scene_command=3), Pause(9, 4000, "b", scene_command=7)]
    jobs = {3: None, 6: 42, 7: 50, 10: 50}
    watch = JobWatch(pauses, sample=lambda pid: jobs[current])
    for current in sorted(jobs):
        watch(current, 1)
    watch(4, 1)  # not a sampling point
    assert watch.busy(pauses[0]), "the scene started job 42 and it still runs"
    assert not watch.busy(pauses[1]), "job 50 ran before the scene (an editor, tmux)"


def _stat(proc: Path, pid: int, name: str, ppid: int, pgrp: int, tpgid: int) -> None:
    (proc / str(pid)).mkdir(parents=True)
    fields = f"S {ppid} {pgrp} {pgrp} 34816 {tpgid} 4194560 0 0"
    (proc / str(pid) / "stat").write_text(f"{pid} ({name}) {fields}\n", encoding="utf-8")


@pytest.fixture
def proc(tmp_path: Path) -> Path:
    root = tmp_path / "proc"
    _stat(root, 10, "vhs", 1, 10, -1)
    _stat(root, 11, "ttyd", 10, 10, -1)
    return root


def _shell(proc: Path, tpgid: int, tty_path: str) -> None:
    _stat(proc, 12, "bash", 11, 12, tpgid)
    (proc / "12" / "fd").mkdir()
    (proc / "12" / "fd" / "0").symlink_to(tty_path)


def test_running_command_is_none_at_the_prompt(proc: Path) -> None:
    _shell(proc, 12, "/dev/null")
    assert running_command(10, proc) is None


def test_running_command_without_a_shell(proc: Path) -> None:
    assert running_command(10, proc) is None
    assert running_command(10, proc.parent / "missing") is None


def test_running_command_tells_commands_from_interactive_programs(proc: Path) -> None:
    master, slave = os.openpty()
    try:
        _shell(proc, 99, os.ttyname(slave))
        assert running_command(10, proc) == 99, "a terminal in line mode: a command runs"
        tty.setraw(slave)
        assert running_command(10, proc) is None, "raw mode: an interactive program waits for keys"
    finally:
        os.close(master)
        os.close(slave)
