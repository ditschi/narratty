"""``build --watch``: what is watched and when it rebuilds."""

from __future__ import annotations

import os
from pathlib import Path

from narratty.errors import UsageError
from narratty.watch import stamp, watch, watched_files

SPEC = """\
cache: {inputs: ["data/*.txt"]}
scenes:
  - id: a
    actions: [{browser: page.html}]
  - id: b
    actions: [{browser: "https://example.org"}]
"""


def test_watched_files_are_the_spec_and_what_it_names(tmp_path: Path) -> None:
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text(SPEC, encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.txt").write_text("1", encoding="utf-8")
    (tmp_path / "narratty.lexicon.toml").write_text("", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    names = {
        path.relative_to(tmp_path.resolve())
        for path in watched_files(spec)
        if tmp_path.resolve() in path.parents
    }
    assert names == {
        Path("demo.narratty.yaml"),
        Path("data/x.txt"),
        Path("page.html"),
        Path("narratty.lexicon.toml"),
        Path("config/lexicon.toml"),  # the user's lexicon (not there yet, but creating it counts)
    }


def test_a_spec_that_does_not_parse_is_watched_alone(tmp_path: Path) -> None:
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text("scenes: [", encoding="utf-8")
    assert watched_files(spec) == [spec.resolve()]


def test_stamp_notes_changes_and_missing_files(tmp_path: Path) -> None:
    file = tmp_path / "a"
    file.write_text("1", encoding="utf-8")
    first = stamp([file, tmp_path / "gone"])
    assert first[tmp_path / "gone"] == 0.0
    os.utime(file, (1, 1))
    assert stamp([file, tmp_path / "gone"]) != first


def test_watch_builds_again_after_a_change(tmp_path: Path) -> None:
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text("scenes: [{id: a}]\n", encoding="utf-8")
    runs: list[int] = []
    said: list[str] = []
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:  # nothing changed yet, then the user saves
            os.utime(spec, (10**9, 10**9))

    watch(spec, lambda: runs.append(len(runs)), say=said.append, sleep=sleep, rounds=2)
    assert runs == [0, 1]
    assert said[0].startswith("watching") and "change detected" in said


def test_a_failed_build_is_reported_and_waited_out(tmp_path: Path, capsys: object) -> None:
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text("scenes: [{id: a}]\n", encoding="utf-8")
    calls = 0

    def build() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise UsageError("bad flag")

    def sleep(seconds: float) -> None:
        os.utime(spec, (10**9 + calls, 10**9 + calls))

    watch(spec, build, say=lambda message: None, sleep=sleep, rounds=2)
    assert calls == 2
