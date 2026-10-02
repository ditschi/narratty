"""Scene selection, section keys and the cached recordings."""

from __future__ import annotations

from pathlib import Path

import pytest

from narratty.build import Plan
from narratty.cache import Segment, SegmentCache, SegmentMeta
from narratty.errors import RenderError, UsageError
from narratty.incremental import (
    chain,
    inputs_digest,
    needed,
    positions_and_inserts,
    ran_spec,
    runs_everything,
    schedule,
    select_plan,
    select_scenes,
)
from narratty.render.script import CARD, HEAD, TAIL, Partial
from narratty.spec.loader import parse_spec
from narratty.timeline import build_timeline

SPEC = """\
end_card: {enabled: true}
timing: {lead_in_ms: 300, tail_ms: 500}
scenes:
  - id: setup
    hidden: true
    actions: [{run: mkdir demo}]
  - id: one
    narration: One.
    actions: [{run: ls}]
  - id: two
    narration: Two.
    actions: [{run: pwd}]
  - id: three
    narration: Three.
    actions: [{run: date}]
"""

LONG = 6000  # a narration this long gives every scene a pause the build shortens


def make_plan(tmp_path: Path, text: str = SPEC, audio_ms: int = LONG, *, draft: bool = False) -> Plan:
    path = tmp_path / "demo.narratty.yaml"
    spec = parse_spec(text, path)
    timeline = build_timeline(spec, {scene.id: audio_ms for scene in spec.scenes})
    return Plan(path, spec, (), timeline, draft=draft)


def keys(planned: Plan, *, fast: bool = True) -> dict[str, str]:
    return {link.label: link.key for link in chain(planned, fast=fast, framerate=30)}


@pytest.mark.parametrize(
    ("ranges", "expected"),
    [
        (["two"], ["two"]),
        (["one:two"], ["one", "two"]),
        (["two:"], ["two", "three"]),
        ([":one"], ["setup", "one"]),
        (["three,one"], ["one", "three"]),
        (["one", "three"], ["one", "three"]),
        (["one:two,two:three"], ["one", "two", "three"]),
    ],
)
def test_select_scenes(tmp_path: Path, ranges: list[str], expected: list[str]) -> None:
    assert select_scenes(make_plan(tmp_path).spec, ranges) == expected


def test_select_scenes_names_the_close_match(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="unknown scene 'tow'") as error:
        select_scenes(make_plan(tmp_path).spec, ["tow"])
    assert "two" in (error.value.hint or "")


def test_select_scenes_rejects_a_backwards_range_and_nothing(tmp_path: Path) -> None:
    spec = make_plan(tmp_path).spec
    with pytest.raises(UsageError, match="runs backwards"):
        select_scenes(spec, ["three:one"])
    with pytest.raises(UsageError, match="selects no scene"):
        select_scenes(spec, [" , "])


def test_needed_sections_follow_the_selection(tmp_path: Path) -> None:
    planned = make_plan(tmp_path)
    assert needed(planned) == [HEAD, "one", "two", "three", TAIL, CARD]
    assert needed(planned, ["setup", "two"]) == ["two"]
    assert needed(planned, ["one", "two"]) == [HEAD, "one", "two"]
    assert needed(planned, ["three"]) == ["three", TAIL, CARD]
    with pytest.raises(UsageError, match="hidden"):
        needed(planned, ["setup"])


def test_select_plan_is_a_video_of_the_chosen_scenes(tmp_path: Path) -> None:
    planned = make_plan(tmp_path, audio_ms=1000)
    middle = select_plan(planned, ["two"])
    assert [s.id for s in middle.spec.scenes] == ["two"]
    assert (middle.timeline.lead_in_ms, middle.timeline.tail_ms, middle.timeline.end_card_ms) == (0, 0, 0)
    last = select_plan(planned, ["two", "three"])
    assert (last.timeline.tail_ms, last.timeline.end_card_ms) == (500, 4000)
    assert last.timeline.lead_in_ms == 0
    assert select_plan(planned, ["one"]).timeline.lead_in_ms == 300


def test_artifacts_and_local_pages_need_the_demo_to_run(tmp_path: Path) -> None:
    assert not runs_everything(make_plan(tmp_path).spec)
    artifacts = SPEC.replace("scenes:", "workspace: {artifacts: [out]}\nscenes:")
    assert runs_everything(make_plan(tmp_path, artifacts).spec)
    page = SPEC.replace("actions: [{run: ls}]", "actions: [{browser: page.html}]")
    assert runs_everything(make_plan(tmp_path, page).spec)
    web = SPEC.replace("actions: [{run: ls}]", "actions: [{browser: 'https://example.org'}]")
    assert not runs_everything(make_plan(tmp_path, web).spec)


def test_a_change_re_keys_its_scene_and_every_later_one(tmp_path: Path) -> None:
    before = keys(make_plan(tmp_path))
    after = keys(make_plan(tmp_path, SPEC.replace("run: pwd", "run: pwd -P")))
    assert [label for label in before if before[label] != after[label]] == ["two", "three", TAIL, CARD]


def test_narration_changes_keep_the_keys_of_fast_scenes(tmp_path: Path) -> None:
    short, long = make_plan(tmp_path, audio_ms=3000), make_plan(tmp_path, audio_ms=9000)
    assert keys(short) == keys(long)
    assert keys(short, fast=False) != keys(long, fast=False), "a full-length pause is recorded as it is"


def test_a_scene_that_opts_out_of_fast_keeps_its_pause_in_the_key(tmp_path: Path) -> None:
    text = SPEC.replace("  - id: two\n", "  - id: two\n    fast: false\n")
    short, long = make_plan(tmp_path, text, 3000), make_plan(tmp_path, text, 9000)
    changed = [label for label, key in keys(short).items() if key != keys(long)[label]]
    assert changed == ["two", "three", TAIL, CARD]


def test_keys_depend_on_the_recording_setup_but_not_on_the_spec_text(tmp_path: Path) -> None:
    base = keys(make_plan(tmp_path))
    assert keys(make_plan(tmp_path, SPEC.replace("terminal", "terminal"))) == base
    assert keys(make_plan(tmp_path, "terminal: {width: 900}\n" + SPEC)) != base
    assert keys(make_plan(tmp_path, draft=True)) != base
    narrated = SPEC.replace("narration: One.", "narration: Uno, but a different text.")
    assert keys(make_plan(tmp_path, narrated)) == base


def test_inputs_are_part_of_the_keys(tmp_path: Path) -> None:
    text = "cache: {inputs: ['*.txt']}\n" + SPEC
    (tmp_path / "a.txt").write_text("1", encoding="utf-8")
    first = keys(make_plan(tmp_path, text))
    assert keys(make_plan(tmp_path, text)) == first
    (tmp_path / "a.txt").write_text("2", encoding="utf-8")
    assert keys(make_plan(tmp_path, text)) != first
    assert inputs_digest(tmp_path, ["*.md"]) == inputs_digest(tmp_path, [])


def store(cache: SegmentCache, planned: Plan, *labels: str) -> None:
    for link in chain(planned, fast=True, framerate=30):
        if link.label in labels:
            cache.put(link.key, None, SegmentMeta(0, tuple(1000 for _ in link.pauses_ms)))


def test_schedule_records_what_the_cache_lacks(tmp_path: Path) -> None:
    planned = make_plan(tmp_path)
    links = chain(planned, fast=True, framerate=30)
    cache = SegmentCache(tmp_path / "cache")
    labels = needed(planned)
    job = schedule(planned, links, labels, cache)
    assert job.recorded == tuple(labels) and job.partial is not None and job.partial.last == CARD
    store(cache, planned, HEAD, "one", "three", TAIL, CARD)
    job = schedule(planned, links, labels, cache)
    assert job.recorded == ("two",) and job.partial == Partial(frozenset({"two"}), "two", frozenset())
    assert set(job.cached) == {HEAD, "one", "three", TAIL, CARD}
    store(cache, planned, "two")
    assert schedule(planned, links, labels, cache).partial is None
    assert schedule(planned, links, labels, cache, clean=True).recorded == tuple(labels)


def test_schedule_runs_the_demo_again_when_its_effects_are_needed(tmp_path: Path) -> None:
    planned = make_plan(tmp_path)
    links = chain(planned, fast=True, framerate=30)
    cache = SegmentCache(tmp_path / "cache")
    store(cache, planned, *needed(planned))
    job = schedule(planned, links, needed(planned), cache, run_all=True)
    assert job.recorded == (CARD,) and CARD not in job.cached


def test_replay_pace_comes_from_the_spec_and_from_past_failures(tmp_path: Path) -> None:
    text = SPEC.replace("  - id: one\n", "  - id: one\n    replay: realtime\n")
    planned = make_plan(tmp_path, text)
    links = chain(planned, fast=True, framerate=30)
    cache = SegmentCache(tmp_path / "cache")
    job = schedule(planned, links, ["three"], cache)
    assert job.partial is not None and job.partial.realtime == {"one"}
    cache.mark_realtime(next(link.content for link in links if link.label == "two"))
    job = schedule(planned, links, ["three"], cache)
    assert job.partial is not None and job.partial.realtime == {"one", "two"}


def test_ran_spec_stops_at_the_last_recorded_scene(tmp_path: Path) -> None:
    spec = make_plan(tmp_path).spec
    assert [s.id for s in ran_spec(spec, Partial(frozenset({"one"}), "one")).scenes] == ["setup", "one"]
    assert ran_spec(spec, Partial(frozenset({HEAD}), HEAD)).scenes == []
    assert ran_spec(spec, Partial(frozenset({CARD}), CARD)) is spec


def test_positions_and_inserts_join_the_sections(tmp_path: Path) -> None:
    planned = make_plan(tmp_path)
    links = {link.label: link for link in chain(planned, fast=True, framerate=30)}
    metas = {
        HEAD: SegmentMeta(300),
        "one": SegmentMeta(2000, (1500,), {"end-one": 1900}),
        "two": SegmentMeta(1600, (1500,), {"cue-overlay:two:1": 700}),
        TAIL: SegmentMeta(500),
        CARD: SegmentMeta(1000, (900,)),  # the card's 4 s hold is a shortened pause too
    }
    parts = [(links[label], meta) for label, meta in metas.items()]
    positions, inserts = positions_and_inserts(parts, 25)
    assert positions == {
        "scene-one": 300,
        "end-one": 2200,
        "scene-two": 2300,
        "cue-overlay:two:1": 3000,
        "cue-end": 3900,
        "card": 4400,
    }
    assert [i.frame for i in inserts] == [
        int((300 + 1500 - 250) * 25 / 1000),
        int((2300 + 1500 - 250) * 25 / 1000),
        int((4400 + 900 - 250) * 25 / 1000),
    ]
    planned_ms = [ms for label in metas for ms in links[label].pauses_ms]
    assert [i.count for i in inserts] == [round((ms - 1000) * 25 / 1000) for ms in planned_ms]
    assert planned_ms[-1] == 4000


def test_a_section_with_other_pauses_than_its_tape_is_refused(tmp_path: Path) -> None:
    planned = make_plan(tmp_path)
    link = next(link for link in chain(planned, fast=True, framerate=30) if link.label == "one")
    with pytest.raises(RenderError, match="does not match its tape"):
        positions_and_inserts([(link, SegmentMeta(1000, ()))], 25)


def test_segments_round_trip_and_prune(tmp_path: Path) -> None:
    import os
    import time

    cache = SegmentCache(tmp_path)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"mp4")
    meta = SegmentMeta(1200, (900,), {"end-a": 800})
    assert cache.get("ab" * 32) is None and not cache.has("ab" * 32)
    cache.put("ab" * 32, video, meta)
    cache.put("cd" * 32, None, SegmentMeta(0))
    hit = cache.get("ab" * 32)
    assert hit == Segment(tmp_path / "segments" / "ab" / f"{'ab' * 32}.mp4", meta)
    assert cache.get("cd" * 32) == Segment(None, SegmentMeta(0))
    assert cache.stats().clips == 2
    old = tmp_path / "segments" / "cd" / f"{'cd' * 32}.json"
    os.utime(old, (0, 0))
    assert cache.prune(86400, now=time.time()).clips == 1
    assert not cache.has("cd" * 32) and cache.has("ab" * 32)
    cache.mark_realtime("abc")
    assert cache.realtime("abc") and not cache.realtime("xyz")
    assert cache.prune(-1).clips == 1 and not cache.has("ab" * 32)
    assert not cache.realtime("abc")


def test_a_recording_without_its_video_is_a_miss(tmp_path: Path) -> None:
    cache = SegmentCache(tmp_path)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"mp4")
    cache.put("ab" * 32, video, SegmentMeta(1000))
    (tmp_path / "segments" / "ab" / f"{'ab' * 32}.mp4").unlink()
    assert cache.get("ab" * 32) is None
