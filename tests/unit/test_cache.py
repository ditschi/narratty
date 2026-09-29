"""Audio cache keys and storage."""

from __future__ import annotations

import os
import time
from pathlib import Path

from narratty.cache import AudioCache, clip_key
from narratty.paths import cache_dir, data_dir
from tests.helpers import write_tone

BASE = {"provider": "piper", "voice": "v", "text": "Hi.", "model_version": "1", "options": {"a": 1, "b": 2}}


def test_key_is_stable_and_ignores_option_order() -> None:
    key = clip_key(**BASE)  # type: ignore[arg-type]
    assert key == clip_key("piper", "v", "Hi.", "1", {"b": 2, "a": 1})
    assert len(key) == 64


def test_key_changes_with_every_input() -> None:
    key = clip_key(**BASE)  # type: ignore[arg-type]
    for field, value in [("voice", "w"), ("text", "Hi!"), ("model_version", "2"), ("options", {"a": 2})]:
        assert clip_key(**{**BASE, field: value}) != key, field  # type: ignore[arg-type]


def test_put_get_and_stats(tmp_path: Path) -> None:
    cache = AudioCache(tmp_path / "c")
    assert cache.get("ab" * 32) is None
    stored = cache.put("ab" * 32, write_tone(tmp_path / "t.wav", 100))
    assert stored == tmp_path / "c" / "audio" / "ab" / f"{'ab' * 32}.wav"
    assert cache.get("ab" * 32) == stored
    stats = cache.stats()
    assert (stats.clips, stats.bytes) == (1, stored.stat().st_size)


def test_prune_removes_only_stale_clips(tmp_path: Path) -> None:
    cache = AudioCache(tmp_path)
    old = cache.put("aa" * 32, write_tone(tmp_path / "a.wav", 10))
    new = cache.put("bb" * 32, write_tone(tmp_path / "b.wav", 10))
    now = time.time()
    os.utime(old, (now - 40 * 86400, now - 40 * 86400))
    removed = cache.prune(30 * 86400, now=now)
    assert removed.clips == 1
    assert not old.exists() and new.exists()


def test_a_hit_protects_a_clip_from_pruning(tmp_path: Path) -> None:
    cache = AudioCache(tmp_path)
    clip = cache.put("aa" * 32, write_tone(tmp_path / "a.wav", 10))
    os.utime(clip, (0, 0))
    cache.get("aa" * 32)
    assert cache.prune(86400).clips == 0


def test_dirs_follow_environment_overrides(tmp_path: Path) -> None:
    env = {"NARRATTY_DATA_DIR": str(tmp_path / "d"), "NARRATTY_CACHE_DIR": "~/c"}
    assert data_dir(env) == tmp_path / "d"
    assert cache_dir(env) == Path("~/c").expanduser()
    assert data_dir({}).name == "narratty"
    assert cache_dir({}).name == "narratty"
