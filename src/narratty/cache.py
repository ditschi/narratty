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
from dataclasses import dataclass
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
