"""The recording script for the editor layout and the diff action."""

from __future__ import annotations

from pathlib import Path

from narratty import diff, editor, sh
from narratty.render.script import (
    CARD,
    HEAD,
    SETUP,
    TAIL,
    Ctrl,
    Cue,
    HelperPlacement,
    Hide,
    Mark,
    Partial,
    Press,
    Show,
    Sleep,
    Step,
    TimelapseEnd,
    Type,
    WaitScreen,
    build_script,
    sections,
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
    marked = f"sh -c ': {editor.MARK}; {sh.need(editor.TOOLS, 'the editor layout', 'on this machine')}; "
    assert start.startswith(marked)
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


MIXED = """\
terminal: {prompt: "> "}
end_card: {enabled: true}
scenes:
  - id: before
    narration: Plain.
  - id: open
    narration: Editor.
    layout: editor
    actions: [{reveal: src}, {focus: terminal}]
  - id: still
    narration: Still the editor.
    actions: [{focus: explorer}]
  - id: mid
    narration: Switch in the middle.
    actions:
      - run: ls
      - layout: plain
      - run: pwd
      - layout: editor
      - focus: explorer
  - id: after
    narration: Plain again.
    layout: plain
    actions: [{run: ls}]
"""

AUDIO = {"before": 1000, "open": 1000, "still": 1000, "mid": 1000, "after": 1000}


def _starts(steps: list[Step]) -> list[Step]:
    return [s for s in steps if isinstance(s, Type) and "exec tmux" in s.text]


def test_a_scene_layout_starts_the_editor_there_and_it_stays_for_later_scenes() -> None:
    steps = _script(MIXED, AUDIO)
    assert Type("PS1='> '; clear", 1) in steps[: steps.index(Show())], "the setup stays a plain shell"
    assert len(_starts(steps)) == 2, "once for `open`, once for the switch back in `mid`"
    open_scene = _scene(steps, "open")
    start = _starts(open_scene)[0]
    assert start.text.startswith(f"{sh.CLEAR}; sh -c ': {editor.MARK}; ")
    assert open_scene[0] == Hide() and open_scene.index(start) == 1
    assert WaitScreen("Terminal", 15_000, fail=sh.ERROR) in open_scene
    still = _scene(steps, "still")
    assert still[:7] == [Hide(), *_tmux("select-pane -t :.1"), Sleep(100), Show()]
    assert not _starts(still) and Type("kill-server", 1) not in still


def test_a_layout_action_switches_between_actions() -> None:
    mid = _scene(_script(MIXED, AUDIO), "mid")
    stop = mid.index(Type("kill-server", 1))
    assert Type("ls", 40) in mid[:stop] and Type("pwd", 40) in mid[stop:]
    assert mid[stop - 3 : stop + 5] == [
        Hide(),
        Ctrl("B"),
        Type(":", 1),
        Type("kill-server", 1),
        Press("Enter", 1),
        Sleep(500),
        Type("clear", 1),
        Press("Enter", 1),
    ]
    assert len(_starts(mid)) == 1 and mid.index(_starts(mid)[0]) > stop


def test_going_back_to_plain_clears_the_screen_and_drops_the_tmux_session() -> None:
    steps = _script(MIXED, AUDIO)
    after = _scene(steps, "after")
    assert after[:3] == [Hide(), Ctrl("B"), Type(":", 1)]
    assert Type("kill-server", 1) in after
    assert Type("kill-server", 1) not in steps[steps.index(Mark(None)) :], "no tmux left for the end card"


def test_a_layout_that_is_already_in_use_changes_nothing() -> None:
    text = (
        "terminal: {layout: editor}\nscenes:\n  - id: a\n    layout: editor\n    actions: [{layout: editor}]"
    )
    assert len(_starts(_script(text, {"a": 1000}))) == 1


def test_the_end_card_leaves_the_editor_only_when_the_last_scene_is_in_it() -> None:
    text = "end_card: {enabled: true}\nscenes:\n  - id: a\n    layout: editor\n"
    steps = _script(text, {"a": 1000})
    card = steps.index(Mark(None))
    assert steps[card - 7 : card] == [Hide(), *_tmux("kill-server"), Sleep(500), Show()]


def test_a_helper_error_ends_the_waits() -> None:
    waits = [s for s in _script(EDITOR) if isinstance(s, WaitScreen) and s.pattern != "Created with narratty"]
    assert len(waits) == 2 and all(w.fail == sh.ERROR for w in waits)


PARTIAL = """\
end_card: {enabled: true}
timing: {lead_in_ms: 300, tail_ms: 500}
scenes:
  - id: prep
    hidden: true
    actions: [{run: mkdir demo}]
  - id: one
    narration: One.
    actions: [{run: ls}, {overlay: Note}]
  - id: two
    narration: Two.
    actions: [{run: pwd}]
  - id: three
    narration: Three.
    actions: [{run: date}]
"""


def _sections(partial: Partial | None = None) -> dict[str, list[Step]]:
    spec = parse_spec(PARTIAL, Path("t.narratty.yaml"))
    timeline = build_timeline(spec, {"one": 8000, "two": 8000, "three": 8000})
    parts = sections(spec, timeline, python="python", partial=partial)
    return dict(parts)


def test_sections_cover_the_whole_script() -> None:
    spec = parse_spec(PARTIAL, Path("t.narratty.yaml"))
    timeline = build_timeline(spec, {"one": 8000, "two": 8000, "three": 8000})
    parts = _sections()
    assert list(parts) == [SETUP, HEAD, "prep", "one", "two", "three", TAIL, CARD]
    assert [step for steps in parts.values() for step in steps] == build_script(
        spec, timeline, python="python"
    )


def test_a_partial_script_replays_the_scenes_before_the_recorded_one() -> None:
    parts = _sections(Partial(frozenset({"three"}), "three"))
    assert list(parts) == [SETUP, "prep", "one", "two", "three"]
    assert Show() not in parts[SETUP] and parts[SETUP][0] == Hide()
    for label in ("prep", "one", "two"):
        assert not any(isinstance(step, Hide | Show | Cue | TimelapseEnd) for step in parts[label]), label
    replayed = parts["one"]
    assert Mark("one", True) in replayed and not any(isinstance(s, WaitScreen) for s in replayed)
    assert Type("ls", 5) in replayed, "typing is quick"
    assert any(isinstance(s, Sleep) and s.replayed and s.ms == 1000 for s in replayed), "a long pause is cut"
    assert parts["three"][:2] == [Sleep(300), Show()] and Mark("three") in parts["three"]


def test_a_realtime_replay_keeps_the_pace() -> None:
    quick = _sections(Partial(frozenset({"two"}), "two"))["one"]
    slow = _sections(Partial(frozenset({"two"}), "two", frozenset({"one"})))["one"]
    assert Type("ls", 40) in slow and Type("ls", 5) in quick
    assert not any(isinstance(s, Sleep) and s.replayed for s in slow)
    assert any(isinstance(s, Sleep) and s.ms > 1000 for s in slow)


def test_recorded_sections_between_replayed_ones_show_again() -> None:
    parts = _sections(Partial(frozenset({"one", "three"}), "three"))
    assert parts["one"][:2] == [Sleep(300), Show()]
    assert parts["two"][0] == Hide(), "recording stops while a scene is replayed"
    assert parts["three"][:2] == [Sleep(300), Show()]


def test_a_head_only_script_stops_after_the_lead_in() -> None:
    parts = _sections(Partial(frozenset({HEAD}), HEAD))
    assert list(parts) == [SETUP, HEAD]
    assert parts[HEAD] == [Sleep(300), Show(), Sleep(300)]


def test_the_end_card_is_recorded_after_a_replayed_tail() -> None:
    parts = _sections(Partial(frozenset({CARD}), CARD))
    assert list(parts) == [SETUP, "prep", "one", "two", "three", TAIL, CARD]
    assert parts[TAIL] == [], "the tail is not recorded and recording is still off"
    assert parts[CARD][:2] == [Sleep(300), Show()]
