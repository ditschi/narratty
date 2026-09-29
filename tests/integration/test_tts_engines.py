"""Real Piper and Kokoro synthesis (downloads the voices on first run)."""

from __future__ import annotations

import importlib.util
import wave
from array import array
from pathlib import Path

import pytest
from typer.testing import CliRunner

from narratty.cli.app import app
from narratty.paths import data_dir
from narratty.tts.audio import wav_duration_ms
from narratty.tts.registry import get_provider
from tests.helpers import plain

pytestmark = pytest.mark.integration

TEXT = "Hello from narratty. This line was spoken by a local voice."


def _peak(path: Path) -> int:
    with wave.open(str(path), "rb") as wav:
        assert wav.getnchannels() == 1 and wav.getsampwidth() == 2
        samples = array("h", wav.readframes(wav.getnframes()))
    return max(abs(s) for s in samples)


def _speak(provider_name: str, voice: str, options: dict[str, object], out: Path) -> Path:
    provider = get_provider(provider_name, data_dir())
    assert provider.unavailable_reason() is None
    if not provider.is_installed(voice):
        provider.install(voice, show_progress=False)
    provider.synthesize(TEXT, voice, out, options)
    return out


def test_piper_speaks(tmp_path: Path) -> None:
    clip = _speak(
        "piper", "en_US-lessac-medium", {"length_scale": 1.0, "sentence_silence": 0.2}, tmp_path / "p.wav"
    )
    assert 2000 < wav_duration_ms(clip) < 10000
    assert _peak(clip) > 1000, "clip is silent"


@pytest.mark.skipif(importlib.util.find_spec("kokoro_onnx") is None, reason="needs narratty[kokoro]")
def test_kokoro_speaks(tmp_path: Path) -> None:
    clip = _speak("kokoro", "af_heart", {"speed": 1.0, "lang": None}, tmp_path / "k.wav")
    assert 2000 < wav_duration_ms(clip) < 10000
    assert _peak(clip) > 1000, "clip is silent"


def test_tts_command_caches_clips(tmp_path: Path) -> None:
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text(
        "scenes:\n  - id: intro\n    narration: A short first line.\n"
        "  - id: outro\n    narration: And a second one.\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    first = runner.invoke(app, ["tts", str(spec)], env={"COLUMNS": "200"})
    assert first.exit_code == 0, first.output
    assert plain(first.output).count(" new ") == 2
    second = runner.invoke(app, ["tts", str(spec)], env={"COLUMNS": "200"})
    assert plain(second.output).count(" hit ") == 2
