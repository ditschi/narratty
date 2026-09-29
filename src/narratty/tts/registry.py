"""Find TTS providers by name.

Third-party providers register a factory under the ``narratty.tts`` entry-point
group; the factory is called with the provider's data directory.
"""

from __future__ import annotations

import difflib
from collections.abc import Callable
from importlib.metadata import entry_points
from pathlib import Path

from narratty.errors import MissingDependencyError
from narratty.tts.base import TtsProvider

ENTRY_POINT_GROUP = "narratty.tts"

ProviderFactory = Callable[[Path], TtsProvider]


def _builtin_factories() -> dict[str, ProviderFactory]:
    from narratty.tts.kokoro import KokoroProvider
    from narratty.tts.piper import PiperProvider

    return {"piper": PiperProvider, "kokoro": KokoroProvider}


def provider_names() -> list[str]:
    """Built-in provider names followed by any registered through entry points."""
    names = ["piper", "kokoro"]
    names += sorted(ep.name for ep in entry_points(group=ENTRY_POINT_GROUP) if ep.name not in names)
    return names


def get_provider(name: str, data_dir: Path) -> TtsProvider:
    """Instantiate the provider called ``name``, storing its files under ``data_dir``."""
    factories = _builtin_factories()
    if name in factories:
        return factories[name](data_dir / name)
    for ep in entry_points(group=ENTRY_POINT_GROUP, name=name):
        factory: ProviderFactory = ep.load()
        return factory(data_dir / name)
    close = difflib.get_close_matches(name, provider_names(), n=1)
    suggestion = f" (did you mean {close[0]!r}?)" if close else ""
    raise MissingDependencyError(
        f"unknown TTS provider {name!r}{suggestion}",
        hint=f"Built-in providers: {', '.join(provider_names())}.",
    )
