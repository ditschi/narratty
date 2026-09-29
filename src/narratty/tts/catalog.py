"""The curated voice catalog shipped as ``narratty/data/voices.toml``.

Reading it needs only ``tomllib``, so shell completion can list voices without
importing any TTS engine.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Any

PROVIDERS = ("piper", "kokoro")


@dataclass(frozen=True)
class RemoteFile:
    """A file to download, with an optional pinned checksum."""

    name: str
    url: str
    sha256: str | None = None


@dataclass(frozen=True)
class CatalogVoice:
    """One curated voice."""

    provider: str
    id: str
    description: str
    language: str
    card_url: str


@cache
def _raw() -> dict[str, Any]:
    text = files("narratty").joinpath("data/voices.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)


def piper_voice_path(voice_id: str) -> str:
    """Relative path of a Piper voice in the upstream repository, without suffix.

    ``en_US-lessac-medium`` lives at ``en/en_US/lessac/medium/en_US-lessac-medium``.
    """
    language, name, quality = voice_id.split("-", 2)
    family = language.split("_", 1)[0]
    return f"{family}/{language}/{name}/{quality}/{voice_id}"


def piper_files(voice_id: str) -> list[RemoteFile]:
    """The model and config files of a Piper voice."""
    base = _raw()["piper"]["base_url"]
    path = piper_voice_path(voice_id)
    return [RemoteFile(f"{voice_id}{suffix}", f"{base}/{path}{suffix}") for suffix in (".onnx", ".onnx.json")]


def kokoro_files() -> list[RemoteFile]:
    """The Kokoro model and voice pack (shared by every Kokoro voice)."""
    return [RemoteFile(**entry) for entry in _raw()["kokoro"]["files"]]


def kokoro_model_version() -> str:
    """Version of the pinned Kokoro model (part of the audio cache key)."""
    return str(_raw()["kokoro"]["version"])


def kokoro_language(voice_id: str) -> str:
    """Language code Kokoro should use for a voice, from the id's first letter."""
    languages: dict[str, str] = _raw()["kokoro"]["languages"]
    return languages.get(voice_id[:1], "en-us")


def voices(provider: str | None = None) -> list[CatalogVoice]:
    """Curated voices, optionally of one provider."""
    raw = _raw()
    result: list[CatalogVoice] = []
    for name in PROVIDERS if provider is None else (provider,):
        section = raw.get(name, {})
        for entry in section.get("voices", []):
            voice_id = entry["id"]
            if name == "piper":
                language = voice_id.split("-", 1)[0]
                card = f"{section['card_url']}/{piper_voice_path(voice_id).rsplit('/', 1)[0]}/MODEL_CARD"
            else:
                language = kokoro_language(voice_id)
                card = section["card_url"]
            result.append(CatalogVoice(name, voice_id, entry["description"], language, card))
    return result


def voice_ids(provider: str | None = None) -> list[str]:
    """Ids of the curated voices."""
    return [voice.id for voice in voices(provider)]
