"""Measured command durations: matching, storing and planning with them."""

from __future__ import annotations

import json
from pathlib import Path

from narratty import durations
from narratty.durations import DurationStore, command_key, match_runs
from narratty.render.script import Sleep, build_script
from narratty.spec.loader import parse_spec
from narratty.spec.model import Spec
from narratty.timeline import MEASURED_SETTLE_MS, build_timeline


def _spec(extra: str = "") -> Spec:
    return parse_spec(
        "meta: {title: Demo}\nend_card: false\n"
        f"timing: {{lead_in_ms: 0, tail_ms: 0, run_hold_ms: 500{extra}}}\n"
        "terminal: {typing_speed_ms: 10}\nscenes:\n"
        "  - id: build\n    narration: We build it.\n    actions: [{run: make}, {run: ls}]\n"
        '  - id: test\n    actions: [{run: "cat <<EOF\\nhi\\nEOF"}]\n',
        Path("t.narratty.yaml"),
    )


def test_match_runs_follows_the_submitted_lines_in_order() -> None:
    took = [("PS1=x", 5), ("make", 12000), ("ls", 40), ("cat <<EOF", None), ("hi", None), ("EOF", 30)]
    assert match_runs(_spec(), took) == {("build", 0): 12000, ("build", 1): 40, ("test", 0): 30}


def test_unmeasured_commands_are_left_out() -> None:
    assert match_runs(_spec(), [("make", None)]) == {}


def test_store_round_trip_rounds_up(tmp_path: Path) -> None:
    store = DurationStore(tmp_path)
    store.record(_spec(), {("build", 0): 12_345, ("build", 1): 40})
    assert store.lookup(_spec()) == {("build", 0): 12_400, ("build", 1): 100}


def test_commands_are_not_stored_in_plain_text(tmp_path: Path) -> None:
    spec = parse_spec(
        "end_card: false\nscenes:\n  - id: env\n    hidden: true\n"
        "    actions: [{run: export DEMO_KEY=hunter2}]\n  - id: a\n    actions: [{run: ls}]\n",
        Path("t.narratty.yaml"),
    )
    old = {"x": {"ms": 100, "scene": "env", "command": "export DEMO_KEY=hunter2", "at": 1}}
    (tmp_path / durations.FILE).write_text(json.dumps(old), encoding="utf-8")
    DurationStore(tmp_path).record(spec, {("env", 0): 100, ("a", 0): 100})
    text = (tmp_path / durations.FILE).read_text(encoding="utf-8")
    assert "hunter2" not in text
    assert "DEMO_KEY" not in text
    assert DurationStore(tmp_path).lookup(spec) == {("env", 0): 100, ("a", 0): 100}


def test_a_changed_command_forgets_its_measurement(tmp_path: Path) -> None:
    spec = _spec()
    DurationStore(tmp_path).record(spec, {("build", 0): 3000})
    assert command_key(spec, "build", "make") != command_key(spec, "build", "make all")
    changed = parse_spec(spec.model_dump_json().replace('"make"', '"make all"'), Path("t.narratty.json"))
    assert DurationStore(tmp_path).lookup(changed) == {}


def test_a_broken_file_reads_as_empty(tmp_path: Path) -> None:
    (tmp_path / durations.FILE).write_text("{not json", encoding="utf-8")
    assert DurationStore(tmp_path).lookup(_spec()) == {}


def test_load_logs_slow_commands_and_respects_the_switch(tmp_path: Path) -> None:
    DurationStore(tmp_path).record(_spec(), {("build", 0): 4000, ("build", 1): 10})
    logs: list[str] = []
    assert durations.load(_spec(), tmp_path, logs.append) == {("build", 0): 4000, ("build", 1): 100}
    assert logs == ["waiting for commands as long as `narratty check` measured them: build (4.0s)"]
    assert durations.load(_spec(", measured_durations: false"), tmp_path) == {}


def test_a_slow_command_lengthens_its_scene_and_its_pause() -> None:
    spec = _spec()
    plain = build_timeline(spec, {"build": 1000})
    measured = build_timeline(spec, {"build": 1000}, {("build", 0): 4000, ("build", 1): 50})
    hold = 4000 + MEASURED_SETTLE_MS
    assert measured.scene("build").run_holds == ((0, hold),)
    assert measured.scene("build").action_ms == plain.scene("build").action_ms + hold - 500
    assert measured.scene("build").length_ms > plain.scene("build").length_ms
    assert measured.scene("build").fill_ms == 0
    steps = build_script(spec, measured)
    assert Sleep(hold) in steps and Sleep(500) in steps


def test_check_records_durations_that_later_plans_use(tmp_path: Path) -> None:
    from narratty.build import WorkspaceOptions, check, plan

    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text(
        "meta: {title: Slow}\ntiming: {run_hold_ms: 200}\nterminal: {typing_speed_ms: 5}\nscenes:\n"
        "  - id: slow\n    narration: This takes a moment.\n    actions: [{run: sleep 1.2}]\n"
        "  - id: quick\n    actions: [{run: 'true'}]\n",
        encoding="utf-8",
    )
    logs: list[str] = []
    check(spec, workspace=WorkspaceOptions(mode="rw"), log=logs.append)
    assert any("plans now wait for the slow ones: slow (1." in line for line in logs)
    planned = plan(spec, draft=True)
    [(index, hold)] = planned.timeline.scene("slow").run_holds
    assert index == 0 and 1200 + MEASURED_SETTLE_MS <= hold < 4000
    assert planned.timeline.scene("quick").run_holds == ()
