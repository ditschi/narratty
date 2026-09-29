"""The provider protocol and helpers shared by the providers."""

from __future__ import annotations

import difflib
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Protocol

from narratty.errors import ValidationError


@dataclass(frozen=True)
class VoiceInfo:
    """A voice as shown by ``narratty voices``."""

    provider: str
    id: str
    description: str
    language: str
    installed: bool
    curated: bool = True


class TtsProvider(Protocol):
    """What the pipeline needs from a text-to-speech engine."""

    name: str

    def unavailable_reason(self) -> str | None:
        """Why the engine cannot run here (missing package), or None when it can."""
        ...

    def voices(self) -> list[VoiceInfo]:
        """Curated and locally installed voices."""
        ...

    def is_installed(self, voice: str) -> bool:
        """True when the voice's files are present locally."""
        ...

    def install(self, voice: str, *, show_progress: bool = True) -> None:
        """Download the voice's files."""
        ...

    def model_version(self, voice: str) -> str:
        """Identifies engine + model; part of the audio cache key."""
        ...

    def synthesize(self, text: str, voice: str, out: Path, options: Mapping[str, Any]) -> None:
        """Write the spoken ``text`` as a WAV file to ``out``."""
        ...


def package_version(name: str) -> str:
    """Installed version of a distribution, or ``unknown``."""
    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"


def unknown_voice_error(provider: TtsProvider, voice: str) -> ValidationError:
    """An error for a voice the provider does not know, with a did-you-mean hint."""
    known = [info.id for info in provider.voices()]
    close = difflib.get_close_matches(voice, known, n=1)
    suggestion = f" (did you mean {close[0]!r}?)" if close else ""
    return ValidationError(
        f"unknown {provider.name} voice {voice!r}{suggestion}",
        hint=f"`narratty voices --provider {provider.name}` lists the voices.",
    )
