"""Turn a spec's narration into WAV clips, reusing the audio cache."""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from narratty.cache import AudioCache, clip_key
from narratty.errors import MissingDependencyError
from narratty.spec.model import Spec
from narratty.tts.audio import wav_duration_ms
from narratty.tts.base import TtsProvider
from narratty.tts.lexicon import Lexicon
from narratty.tts.normalize import normalize_text

Log = Callable[[str], None]


@dataclass(frozen=True)
class Clip:
    """One synthesized narration."""

    scene_id: str
    path: Path
    duration_ms: int
    cached: bool


def prepare_voice(provider: TtsProvider, voice: str, *, download: bool, show_progress: bool = True) -> None:
    """Fail early when the provider cannot run, and fetch the voice when allowed."""
    reason = provider.unavailable_reason()
    if reason is not None:
        raise MissingDependencyError(reason, hint="`narratty doctor` shows what is missing.")
    if provider.is_installed(voice):
        return
    if not download:
        raise MissingDependencyError(
            f"{provider.name} voice {voice!r} is not installed",
            hint=f"Run `narratty voices pull {voice} --provider {provider.name}`.",
        )
    provider.install(voice, show_progress=show_progress)


def _synthesize(
    provider: TtsProvider, cache: AudioCache, key: str, text: str, voice: str, options: Mapping[str, Any]
) -> Path:
    with tempfile.TemporaryDirectory(prefix="narratty-tts-") as tmp:
        fresh = Path(tmp) / "clip.wav"
        provider.synthesize(text, voice, fresh, options)
        return cache.put(key, fresh)


def synthesize_spec(
    spec: Spec,
    provider: TtsProvider,
    cache: AudioCache,
    *,
    download: bool = True,
    show_progress: bool = True,
    on_clip: Callable[[Clip], None] | None = None,
    lexicon: Lexicon | None = None,
    log: Log | None = None,
) -> list[Clip]:
    """Synthesize (or fetch from cache) one clip per narrated scene, in scene order.

    ``lexicon`` rewrites the narration into what the engine should say; the rewritten
    text is what the cache key hashes. Missing clips are synthesized up to
    ``provider.concurrency`` at a time; ``on_clip`` still sees them in scene order.
    """
    voice = spec.tts.voice
    prepare_voice(provider, voice, download=download, show_progress=show_progress)
    options = spec.tts.provider_options()
    version = provider.model_version(voice)
    pending: list[tuple[str, str, Path | None]] = []
    missing: dict[str, str] = {}
    for scene in spec.narrated_scenes:
        text = normalize_text(scene.narration or "")
        if lexicon is not None:
            text = lexicon.apply(text)
        key = clip_key(provider.name, voice, text, version, options)
        path = cache.get(key)
        pending.append((scene.id, key, path))
        if path is None:
            missing[key] = text
    if missing and log is not None:
        log(f"{len(missing)} of {len(pending)} narration clips not cached, synthesizing with {provider.name}")
    clips: list[Clip] = []
    with ThreadPoolExecutor(max_workers=max(1, provider.concurrency)) as pool:
        jobs: dict[str, Future[Path]] = {
            key: pool.submit(_synthesize, provider, cache, key, text, voice, options)
            for key, text in missing.items()
        }
        for scene_id, key, path in pending:
            cached = path is not None
            path = path or jobs[key].result()
            clip = Clip(scene_id, path, wav_duration_ms(path), cached)
            clips.append(clip)
            if on_clip is not None:
                on_clip(clip)
    return clips
