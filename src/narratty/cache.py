"""Content-addressed audio cache.

A clip's key hashes everything that changes its sound: provider, voice, the
normalized text, the model version and the provider options. Clips live at
``<cache>/audio/<key[:2]>/<key>.wav``; a hit refreshes the file's mtime so
``prune`` removes what has not been used recently.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def clip_key(provider: str, voice: str, text: str, model_version: str, options: Mapping[str, Any]) -> str:
    """Stable sha256 key of one narration clip."""
    payload = {
        "provider": provider,
        "voice": voice,
        "text": text,
        "model_version": model_version,
        "options": dict(sorted(options.items())),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CacheStats:
    """What ``narratty cache info`` reports."""

    path: Path
    clips: int
    bytes: int


class AudioCache:
    """WAV clips keyed by :func:`clip_key`."""

    def __init__(self, root: Path) -> None:
        self.root = root / "audio"

    def path_for(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.wav"

    def get(self, key: str) -> Path | None:
        """The cached clip, or None. A hit refreshes the clip's mtime."""
        path = self.path_for(key)
        if not path.is_file():
            return None
        path.touch()
        return path

    def put(self, key: str, source: Path) -> Path:
        """Move ``source`` into the cache atomically and return its cached path."""
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        staged = path.with_name(f"{path.name}.{os.getpid()}.part")
        shutil.move(source, staged)  # may cross filesystems; the final rename does not
        os.replace(staged, path)
        return path

    def _clips(self) -> list[Path]:
        return list(self.root.glob("*/*.wav")) if self.root.is_dir() else []

    def stats(self) -> CacheStats:
        clips = self._clips()
        return CacheStats(self.root, len(clips), sum(p.stat().st_size for p in clips))

    def prune(self, older_than_s: float, *, now: float | None = None) -> CacheStats:
        """Delete clips unused for ``older_than_s`` seconds; returns what was removed."""
        cutoff = (time.time() if now is None else now) - older_than_s
        removed = [p for p in self._clips() if p.stat().st_mtime < cutoff]
        size = 0
        for path in removed:
            size += path.stat().st_size
            path.unlink()
        return CacheStats(self.root, len(removed), size)


@dataclass(frozen=True)
class SegmentMeta:
    """What is known about a recorded section besides its video.

    ``pauses_ms``: where each of its shortened pauses ends; ``marks_ms``: where its
    markers (cues, timelapse ends) are; both from the section's start.
    """

    duration_ms: int
    pauses_ms: tuple[int, ...] = ()
    marks_ms: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {"duration_ms": self.duration_ms, "pauses_ms": list(self.pauses_ms), "marks_ms": self.marks_ms},
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, text: str) -> SegmentMeta:
        data = json.loads(text)
        return cls(int(data["duration_ms"]), tuple(data["pauses_ms"]), dict(data["marks_ms"]))


@dataclass(frozen=True)
class Segment:
    """A cached recording: its video (None when it is empty) and metadata."""

    video: Path | None
    meta: SegmentMeta


class SegmentCache:
    """Recordings of single tape sections, keyed by ``narratty.incremental`` chain keys.

    Each is ``<key>.json`` plus ``<key>.mp4`` unless empty, under
    ``<cache>/segments/<key[:2]>/``. ``realtime/`` remembers scenes whose quick replay
    left a command running.
    """

    def __init__(self, root: Path) -> None:
        self.root = root / "segments"

    def _meta(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def has(self, key: str) -> bool:
        """Whether the recording is cached (without refreshing it)."""
        meta = self._meta(key)
        if not meta.is_file():
            return False
        return SegmentMeta.from_json(meta.read_text(encoding="utf-8")).duration_ms == 0 or (
            meta.with_suffix(".mp4").is_file()
        )

    def get(self, key: str) -> Segment | None:
        """The cached recording, or None. A hit refreshes its mtime."""
        if not self.has(key):
            return None
        meta_path = self._meta(key)
        meta = SegmentMeta.from_json(meta_path.read_text(encoding="utf-8"))
        meta_path.touch()
        video = meta_path.with_suffix(".mp4")
        if not meta.duration_ms:
            return Segment(None, meta)
        video.touch()
        return Segment(video, meta)

    def put(self, key: str, video: Path | None, meta: SegmentMeta) -> None:
        """Store a recording (``video`` is moved); the metadata goes last, so a half-stored one misses."""
        meta_path = self._meta(key)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        if video is not None:
            target = meta_path.with_suffix(".mp4")
            staged = target.with_name(f"{target.name}.{os.getpid()}.part")
            shutil.move(video, staged)
            os.replace(staged, target)
        staged = meta_path.with_name(f"{meta_path.name}.{os.getpid()}.part")
        staged.write_text(meta.to_json(), encoding="utf-8")
        os.replace(staged, meta_path)

    def _memo(self, content: str) -> Path:
        return self.root / "realtime" / content

    def realtime(self, content: str) -> bool:
        """Whether the scene with this content must be replayed at its own pace."""
        return self._memo(content).is_file()

    def mark_realtime(self, content: str) -> None:
        """Replay the scene with this content at its own pace from now on."""
        memo = self._memo(content)
        memo.parent.mkdir(parents=True, exist_ok=True)
        memo.touch()

    def _files(self) -> list[Path]:
        return list(self.root.glob("*/*.json")) if self.root.is_dir() else []

    def stats(self) -> CacheStats:
        entries = self._files()
        size = sum(
            p.stat().st_size for meta in entries for p in (meta, meta.with_suffix(".mp4")) if p.is_file()
        )
        return CacheStats(self.root, len(entries), size)

    def prune(self, older_than_s: float, *, now: float | None = None) -> CacheStats:
        """Delete recordings unused for ``older_than_s`` seconds; returns what was removed."""
        cutoff = (time.time() if now is None else now) - older_than_s
        removed, size = 0, 0
        for meta in self._files():
            if meta.stat().st_mtime >= cutoff:
                continue
            removed += 1
            for path in (meta.with_suffix(".mp4"), meta):
                if path.is_file():
                    size += path.stat().st_size
                    path.unlink()
        memos = self.root / "realtime"
        for memo in memos.iterdir() if memos.is_dir() else ():
            if memo.stat().st_mtime < cutoff:
                memo.unlink()
        return CacheStats(self.root, removed, size)
