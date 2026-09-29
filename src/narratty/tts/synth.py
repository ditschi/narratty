"""Turn a spec's narration into WAV clips, reusing the audio cache."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from narratty.cache import AudioCache, clip_key
from narratty.errors import MissingDependencyError
from narratty.spec.model import Spec
from narratty.tts.audio import wav_duration_ms
from narratty.tts.base import TtsProvider
from narratty.tts.normalize import normalize_text


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


def synthesize_spec(
    spec: Spec,
    provider: TtsProvider,
    cache: AudioCache,
    *,
    download: bool = True,
    show_progress: bool = True,
    on_clip: Callable[[Clip], None] | None = None,
) -> list[Clip]:
    """Synthesize (or fetch from cache) one clip per narrated scene, in scene order."""
    voice = spec.tts.voice
    prepare_voice(provider, voice, download=download, show_progress=show_progress)
    options = spec.tts.provider_options()
    version = provider.model_version(voice)
    clips: list[Clip] = []
    for scene in spec.narrated_scenes:
        text = normalize_text(scene.narration or "")
        key = clip_key(provider.name, voice, text, version, options)
        path = cache.get(key)
        cached = path is not None
        if path is None:
            with tempfile.TemporaryDirectory(prefix="narratty-tts-") as tmp:
                fresh = Path(tmp) / "clip.wav"
                provider.synthesize(text, voice, fresh, options)
                path = cache.put(key, fresh)
        clip = Clip(scene.id, path, wav_duration_ms(path), cached)
        clips.append(clip)
        if on_clip is not None:
            on_clip(clip)
    return clips
