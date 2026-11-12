"""Keys for recordings that share scene state."""

from pathlib import Path

from narratty.render.scene_cache import SceneCache, scene_keys, workspace_digest
from narratty.spec.loader import parse_spec
from narratty.timeline import build_timeline

SPEC = """\
end_card: false
scenes:
  - id: first
    narration: Hello.
    actions: [{run: 'echo first'}]
  - id: second
    actions: [{run: 'echo second'}]
  - id: third
    actions: [{run: 'echo third'}]
"""


def _keys(text: str = SPEC, duration: int = 2000, context: str = "workspace") -> dict[str, str]:
    spec = parse_spec(text, Path("demo.narratty.yaml"))
    return scene_keys(spec, build_timeline(spec, {"first": duration}), context)


def test_changes_invalidate_the_scene_and_following_scenes() -> None:
    original = _keys()
    changed = _keys(SPEC.replace("echo second", "echo changed"))
    assert changed["first"] == original["first"]
    assert changed["second"] != original["second"]
    assert changed["third"] != original["third"]


def test_recording_context_and_narration_duration_invalidate_all_later_scenes() -> None:
    original = _keys()
    assert all(_keys(context="other")[key] != value for key, value in original.items())
    assert all(_keys(duration=3000)[key] != value for key, value in original.items())


def test_narration_text_with_the_same_duration_keeps_the_recording() -> None:
    assert _keys(SPEC.replace("Hello.", "Welcome.")) == _keys()


def test_recording_is_shared_by_prefix_keys(tmp_path: Path) -> None:
    cache = SceneCache(tmp_path)
    video = tmp_path / "recording.mp4"
    video.write_bytes(b"video")
    cache.put({"first": "first", "second": "second"}, video, {"first": 100, "second": 2000}, 4000)
    first, second = cache.get("first"), cache.get("second")
    assert first is not None and second is not None
    assert first.video == second.video and (first.cut_ms, second.cut_ms) == (2000, 4000)
    assert first.video.read_bytes() == b"video"
    assert first.starts_ms == {"first": 100, "second": 2000}


def test_damaged_or_missing_cache_entries_are_misses(tmp_path: Path) -> None:
    cache = SceneCache(tmp_path)
    entries = cache.root / "keys"
    entries.mkdir(parents=True)
    (entries / "broken.json").write_text("{", encoding="utf-8")
    (entries / "escape.json").write_text(
        '{"video":"../other.mp4","starts_ms":{},"end_ms":0}', encoding="utf-8"
    )
    assert cache.get("missing") is None
    assert cache.get("broken") is None
    assert cache.get("escape") is None


def test_workspace_digest_detects_changes_and_ignores_explicit_exclusions(tmp_path: Path) -> None:
    source, spec = tmp_path / "source.txt", tmp_path / "demo.yaml"
    source.write_text("one", encoding="utf-8")
    spec.write_text("first spec", encoding="utf-8")
    before = workspace_digest(tmp_path, exclude=frozenset({spec}))
    spec.write_text("second spec", encoding="utf-8")
    assert workspace_digest(tmp_path, exclude=frozenset({spec})) == before
    source.write_text("two", encoding="utf-8")
    assert workspace_digest(tmp_path, exclude=frozenset({spec})) != before


def test_workspace_digest_excludes_entire_directories(tmp_path: Path) -> None:
    excluded = tmp_path / "work"
    excluded.mkdir()
    before = workspace_digest(tmp_path, exclude=frozenset({excluded}))
    (excluded / "result.mp4").write_bytes(b"video")
    assert workspace_digest(tmp_path, exclude=frozenset({excluded})) == before


def test_prune_preserves_recordings_referenced_by_fresh_entries(tmp_path: Path) -> None:
    import os
    import time

    cache = SceneCache(tmp_path)
    video = tmp_path / "recording.mp4"
    video.write_bytes(b"video")
    cache.put({"first": "first", "second": "second"}, video, {"first": 0, "second": 2000}, 4000)
    old = time.time() - 1000
    os.utime(cache.root / "keys" / "first.json", (old, old))
    recording = cache.get("second")
    assert recording is not None
    os.utime(recording.video, (old, old))
    removed = cache.prune(100)
    assert (removed.entries, removed.recordings) == (1, 0)
    assert recording.video.is_file()
    removed = cache.prune(-1)
    assert (removed.entries, removed.recordings, removed.bytes) == (1, 1, 5)
