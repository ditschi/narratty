"""The editor layout with real tmux and yazi, recorded as an asciicast."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from narratty.render.cast import record
from narratty.render.exits import check
from narratty.render.script import build_script
from narratty.spec.loader import parse_spec
from narratty.timeline import build_timeline

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not all(shutil.which(t) for t in ("tmux", "yazi", "ya", "git")), reason="needs tmux and yazi"
    ),
]

SPEC = """\
timing: {lead_in_ms: 0, tail_ms: 0, narration_buffer_ms: 0}
terminal: {layout: editor, typing_speed_ms: 5}
end_card: {enabled: true, duration_ms: 1000}
scenes:
  - id: run
    narration: Change a file.
    actions:
      - type_command: "echo changed > notes.txt"
      - enter
      - reveal: notes.txt
      - focus: explorer
      - diff
      - wait: {screen: "first", timeout_ms: 10000}  # the removed line, only in the diff
"""


def test_layout_actions_and_teardown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NARRATTY_DIFF_BASE", str(tmp_path / "base"))
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("first\n", encoding="utf-8")
    spec = parse_spec(SPEC, tmp_path / "t.narratty.yaml")
    timeline = build_timeline(spec, {"run": 500})
    recording = record(
        build_script(spec, timeline), terminal=spec.terminal, cwd=workspace, env=os.environ, title="T"
    )
    assert "Explorer" in recording.cast and "Terminal" in recording.cast
    assert "Created with narratty" in recording.cast, "the end card is drawn after tmux exits"


MIXED = """\
timing: {lead_in_ms: 0, tail_ms: 0, narration_buffer_ms: 0}
terminal: {typing_speed_ms: 5}
end_card: {enabled: true, duration_ms: 1000}
scenes:
  - id: before
    narration: A plain shell.
    actions:
      - run: echo plain-before
  - id: open
    narration: The editor.
    layout: editor
    actions:
      - reveal: notes.txt
      - focus: terminal
      - run: echo in-the-editor
  - id: after
    narration: Plain again.
    layout: plain
    actions:
      - run: echo plain-after
      - wait: {prompt: true}
"""


def test_a_scene_can_enter_and_leave_the_editor_layout(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("first\n", encoding="utf-8")
    spec = parse_spec(MIXED, tmp_path / "t.narratty.yaml")
    timeline = build_timeline(spec, {"before": 500, "open": 500, "after": 500})
    log = tmp_path / "exits.log"
    log.write_text("", encoding="utf-8")
    recording = record(
        build_script(spec, timeline, exit_log=log),
        terminal=spec.terminal,
        cwd=workspace,
        env=os.environ,
        title="T",
    )
    assert "plain-before" in recording.cast and "Explorer" in recording.cast
    assert "in-the-editor" in recording.cast
    assert "plain-after" in recording.cast, "the shell is back after the layout ended"
    assert "Created with narratty" in recording.cast
    check(spec, log)  # neither the layout's start command nor the plain shell's commands failed
