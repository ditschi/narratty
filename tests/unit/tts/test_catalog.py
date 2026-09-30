"""The curated voice catalog."""

from __future__ import annotations

import re

from narratty.tts import catalog


def test_default_voice_is_curated() -> None:
    assert "en_US-lessac-medium" in catalog.voice_ids("piper")


def test_voice_ids_are_unique_per_provider() -> None:
    for provider in catalog.PROVIDERS:
        ids = catalog.voice_ids(provider)
        assert len(ids) == len(set(ids)), provider


def test_piper_files_follow_the_upstream_layout() -> None:
    model, config = catalog.piper_files("en_US-lessac-medium")
    assert model.url.endswith("/en/en_US/lessac/medium/en_US-lessac-medium.onnx")
    assert config.url.endswith("/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json")
    assert (model.name, config.name) == ("en_US-lessac-medium.onnx", "en_US-lessac-medium.onnx.json")


def test_piper_voice_card_and_language() -> None:
    voice = next(v for v in catalog.voices("piper") if v.id == "en_GB-jenny_dioco-medium")
    assert voice.language == "en_GB"
    assert voice.card_url.endswith("/en/en_GB/jenny_dioco/medium/MODEL_CARD")


def test_kokoro_files_are_pinned() -> None:
    files = catalog.kokoro_files()
    assert [f.name for f in files] == ["kokoro-v1.0.fp16.onnx", "voices-v1.0.bin"]
    assert all(f.sha256 and re.fullmatch(r"[0-9a-f]{64}", f.sha256) for f in files)


def test_kokoro_language_follows_the_voice_prefix() -> None:
    assert catalog.kokoro_language("af_heart") == "en-us"
    assert catalog.kokoro_language("bm_george") == "en-gb"
    assert catalog.kokoro_language("xx_unknown") == "en-us"


def test_all_voices_lists_every_provider() -> None:
    providers = {v.provider for v in catalog.voices()}
    assert providers == set(catalog.PROVIDERS)
