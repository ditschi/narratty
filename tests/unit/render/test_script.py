"""The recording script for the editor layout and the diff action."""

from __future__ import annotations

from pathlib import Path

from narratty import diff, editor, sh
from narratty.render.script import (
    Ctrl,
    HelperPlacement,
    Hide,
    Mark,
    Press,
    Show,
    Sleep,
    Step,
    Type,
    WaitScreen,
    build_script,
)
from narratty.spec.loader import parse_spec
from narratty.timeline import build_timeline

BASE = "/work/diff-base"
HERE = HelperPlacement(diff_base=BASE)

EDITOR = """\
terminal: {layout: editor, prompt: "> "}
end_card: {enabled: true}
scenes:
  - id: look
    narration: Look.
    actions:
      - focus: explorer
      - reveal: src/a b.py
      - diff: [src, README.md]
      - hold: auto
      - type_command: q
  - id: after
    narration: After.
    actions: [diff, {hold: 500}]
  - id: quiet
    hidden: true
    actions: [{type_command: make}, enter]
"""


def _script(
    text: str, audio: dict[str, int] | None = None, placement: HelperPlacement | None = None
) -> list[Step]:
    spec = parse_spec(text, Path("t.narratty.yaml"))
    timeline = build_timeline(spec, audio or {"look": 1000, "after": 1000})
    return build_script(spec, timeline, placement=placement or HERE)


def _scene(steps: list[Step], scene_id: str) -> list[Step]:
    start = next(i for i, s in enumerate(steps) if isinstance(s, Mark) and s.scene_id == scene_id)
    end = next((i for i, s in enumerate(steps[start + 1 :], start + 1) if isinstance(s, Mark)), len(steps))
    return steps[start + 1 : end]


def _tmux(command: str) -> list[Step]:
    return [Ctrl("B"), Type(":", 1), Type(command, 1), Press("Enter", 1)]


def test_setup_records_the_baseline_and_builds_the_layout() -> None:
    steps = _script(EDITOR)
    setup = steps[: steps.index(Show())]
    assert setup[:4] == [
        Hide(),
        Type(diff.start_command(BASE), 1),
        Press("Enter", 1),
        WaitScreen("diff baseline ready", 300_000, fail=sh.ERROR),
    ]
    assert Type("PS1='> '; clear", 1) in setup
    start = next(s.text for s in setup if isinstance(s, Type) and "exec tmux" in s.text)
    assert start.startswith(f"sh -c '{sh.need(editor.TOOLS, 'the editor layout', 'on this machine')}; ")
    assert "bash --noprofile --norc +o history" in start and "PS1=" in start
    assert setup[-3:-1] == [Press("Enter", 1), WaitScreen("Terminal", 15_000, fail=sh.ERROR)]


def test_editor_actions_run_hidden_through_the_tmux_prompt() -> None:
    look = _scene(_script(EDITOR), "look")
    reveal = f"run-shell {sh.tmux_arg(editor.reveal_script('src/a b.py'))}"
    show = sh.tmux_arg(diff.show_script(BASE, ["src", "README.md"], wait=True))
    popup = f'display-popup -E -w 90% -h 85% -T " Diff " {show}'
    assert look[:7] == [Hide(), *_tmux("select-pane -t :.1"), Sleep(100), Show()]
    assert look[7:14] == [Hide(), *_tmux(reveal), Sleep(600), Show()]
    assert look[14:21] == [Hide(), *_tmux(popup), Sleep(1000), Show()]
    # The popup stays through the narration and closes before the next typed key.
    # Fill: 1000 audio + 500 buffer - 40 for typing "q"; the editor actions take no time.
    assert look[21:] == [Sleep(1460), Hide(), Press("Enter", 1), Sleep(300), Show(), Type("q", 40)]


def test_popup_closes_at_the_end_of_the_scene() -> None:
    after = _scene(_script(EDITOR), "after")
    assert after[-6:] == [Sleep(500), Sleep(1000), Hide(), Press("Enter", 1), Sleep(300), Show()]


def test_hidden_scene_clears_the_terminal_pane() -> None:
    quiet = _scene(_script(EDITOR), "quiet")
    assert quiet[:5] == [Hide(), Type("make", 40), Press("Enter", 40), Sleep(100), Ctrl("B")]
    clear = quiet.index(Type("send-keys -t :.2 clear Enter", 1))
    assert quiet[clear + 1 : clear + 4] == [Press("Enter", 1), Sleep(300), Show()]
    assert quiet.count(Show()) == 1 + 1, "one for the scene, one for the teardown after it"


def test_layout_is_left_before_the_end_card() -> None:
    steps = _script(EDITOR)
    card = next(i for i, s in enumerate(steps) if s == Mark(None))
    assert steps[card - 7 : card] == [Hide(), *_tmux("kill-server"), Sleep(500), Show()]


def test_plain_layout_prints_the_diff_in_the_shell() -> None:
    steps = _script("end_card: false\nscenes:\n  - id: after\n    narration: Hi.\n    actions: [diff]\n")
    assert _scene(steps, "after")[:4] == [
        Hide(),
        Type(f"clear; {sh.command(diff.show_script(BASE))}", 1),
        Press("Enter", 1),
        Sleep(1000),
    ]
    assert not any(s == Type("kill-server", 1) for s in steps)


def test_no_baseline_without_diff() -> None:
    steps = _script("scenes:\n  - id: after\n    narration: Hi.\n")
    assert not any(isinstance(s, WaitScreen) for s in steps)


def test_the_terminal_pane_can_be_a_bridge_while_the_recorder_shell_stays_local() -> None:
    bridged = HelperPlacement(diff_base=BASE, terminal="docker exec -it env bash")
    setup = _script(EDITOR, placement=bridged)
    start = next(s.text for s in setup if isinstance(s, Type) and "exec tmux" in s.text)
    assert "docker exec -it env bash" in start
    assert Type("PS1='> '; clear", 1) in setup, "the local shell's prompt, set before tmux starts"


def test_a_helper_error_ends_the_waits() -> None:
    waits = [s for s in _script(EDITOR) if isinstance(s, WaitScreen) and s.pattern != "Created with narratty"]
    assert len(waits) == 2 and all(w.fail == sh.ERROR for w in waits)
