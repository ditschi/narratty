"""Kokoro provider via ``kokoro-onnx`` (the default provider).

Every Kokoro voice shares one ONNX model and one voice pack, stored in
``<data>/kokoro``.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from narratty.errors import MissingDependencyError
from narratty.tts import catalog
from narratty.tts.audio import write_wav
from narratty.tts.base import VoiceInfo, package_version, unknown_voice_error
from narratty.tts.download import download


class KokoroEngine(Protocol):
    """The part of ``kokoro_onnx.Kokoro`` narratty uses."""

    def create(self, text: str, voice: str, speed: float, lang: str) -> tuple[Any, int]: ...

    def get_voices(self) -> Sequence[str]: ...


EngineFactory = Callable[[Path, Path], KokoroEngine]


def _load_engine(model: Path, voices: Path) -> KokoroEngine:
    from kokoro_onnx import Kokoro

    engine: KokoroEngine = Kokoro(str(model), str(voices))
    return engine


class KokoroProvider:
    """Synthesizes in-process with kokoro-onnx."""

    name = "kokoro"

    def __init__(self, model_dir: Path, *, engine_factory: EngineFactory | None = None) -> None:
        self.model_dir = model_dir
        self._factory = engine_factory
        self._engine: KokoroEngine | None = None

    def unavailable_reason(self) -> str | None:
        if self._factory is None and importlib.util.find_spec("kokoro_onnx") is None:
            return "kokoro-onnx is not installed (reinstall narratty)"
        return None

    def _files(self) -> list[Path]:
        return [self.model_dir / file.name for file in catalog.kokoro_files()]

    def _models_present(self) -> bool:
        return all(path.is_file() for path in self._files())

    def is_installed(self, voice: str) -> bool:
        if not self._models_present():
            return False
        return voice in catalog.voice_ids(self.name) or voice in self._engine_voices()

    def _engine_voices(self) -> Sequence[str]:
        try:
            return self._get_engine().get_voices()
        except MissingDependencyError:
            return ()

    def voices(self) -> list[VoiceInfo]:
        installed = self._models_present()
        return [
            VoiceInfo(self.name, v.id, v.description, v.language, installed)
            for v in catalog.voices(self.name)
        ]

    def install(self, voice: str, *, show_progress: bool = True) -> None:
        for file in catalog.kokoro_files():
            if not (self.model_dir / file.name).is_file():
                download(file, self.model_dir, show_progress=show_progress)
        if not self.is_installed(voice):
            raise unknown_voice_error(self, voice)

    def model_version(self, voice: str) -> str:
        _ = voice
        return f"kokoro-onnx {package_version('kokoro-onnx')}; model {catalog.kokoro_model_version()}"

    def _get_engine(self) -> KokoroEngine:
        if self._engine is None:
            reason = self.unavailable_reason()
            if reason is not None:
                raise MissingDependencyError(reason, hint="Install it, or use `tts.provider: piper`.")
            model, voices = self._files()
            self._engine = (self._factory or _load_engine)(model, voices)
        return self._engine

    def synthesize(self, text: str, voice: str, out: Path, options: Mapping[str, Any]) -> None:
        lang = options.get("lang") or catalog.kokoro_language(voice)
        speed = float(options.get("speed", 1.0))
        samples, rate = self._get_engine().create(text, voice=voice, speed=speed, lang=lang)
        write_wav(out, samples, rate)
