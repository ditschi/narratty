"""Piper and Kokoro providers with their engines replaced by fakes."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from narratty.errors import MissingDependencyError, RenderError, ValidationError
from narratty.tts import catalog
from narratty.tts.audio import wav_duration_ms
from narratty.tts.base import TtsProvider
from narratty.tts.kokoro import KokoroProvider
from narratty.tts.piper import PiperProvider
from narratty.tts.registry import get_provider, provider_names
from tests.helpers import write_tone


def _install_piper_voice(voice_dir: Path, voice: str = "en_US-lessac-medium") -> None:
    voice_dir.mkdir(parents=True, exist_ok=True)
    (voice_dir / f"{voice}.onnx").write_bytes(b"onnx")
    (voice_dir / f"{voice}.onnx.json").write_text('{"audio": {"sample_rate": 22050}}', encoding="utf-8")


class FakePiper:
    """Records argv and writes a tone where Piper would write its WAV."""

    def __init__(self, returncode: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.returncode = returncode

    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        argv = list(argv)
        self.calls.append(argv)
        if self.returncode == 0:
            write_tone(Path(argv[argv.index("--output-file") + 1]), 500)
        return subprocess.CompletedProcess(argv, self.returncode, "", "boom\nvoice exploded")


def test_registry_knows_the_builtins(tmp_path: Path) -> None:
    assert provider_names()[:2] == ["piper", "kokoro"]
    assert isinstance(get_provider("piper", tmp_path), PiperProvider)
    assert isinstance(get_provider("kokoro", tmp_path), KokoroProvider)


def test_registry_suggests_close_names(tmp_path: Path) -> None:
    with pytest.raises(MissingDependencyError, match="did you mean 'piper'"):
        get_provider("pipr", tmp_path)


def test_providers_satisfy_the_protocol(tmp_path: Path) -> None:
    providers: list[TtsProvider] = [PiperProvider(tmp_path), KokoroProvider(tmp_path)]
    assert [p.name for p in providers] == ["piper", "kokoro"]


def test_piper_command_line(tmp_path: Path) -> None:
    _install_piper_voice(tmp_path)
    fake = FakePiper()
    provider = PiperProvider(tmp_path, command=["piper"], runner=fake)
    out = tmp_path / "clip.wav"
    provider.synthesize(
        "Hello there.", "en_US-lessac-medium", out, {"length_scale": 1.2, "sentence_silence": 0.3}
    )
    argv = fake.calls[0]
    assert argv[0] == "piper"
    assert argv[argv.index("--model") + 1] == str(tmp_path / "en_US-lessac-medium.onnx")
    assert argv[argv.index("--length-scale") + 1] == "1.2"
    assert argv[argv.index("--sentence-silence") + 1] == "0.3"
    assert wav_duration_ms(out) == 500


def test_piper_failure_is_a_render_error(tmp_path: Path) -> None:
    _install_piper_voice(tmp_path)
    provider = PiperProvider(tmp_path, command=["piper"], runner=FakePiper(returncode=1))
    with pytest.raises(RenderError, match="voice exploded"):
        provider.synthesize("Hi.", "en_US-lessac-medium", tmp_path / "clip.wav", {})


def test_piper_lists_curated_and_local_voices(tmp_path: Path) -> None:
    _install_piper_voice(tmp_path)
    _install_piper_voice(tmp_path, "xx_XX-custom-low")
    voices = {v.id: v for v in PiperProvider(tmp_path).voices()}
    assert voices["en_US-lessac-medium"].installed
    assert not voices["en_US-amy-medium"].installed
    assert voices["xx_XX-custom-low"].curated is False


def test_piper_model_version_changes_with_the_config(tmp_path: Path) -> None:
    _install_piper_voice(tmp_path)
    provider = PiperProvider(tmp_path)
    before = provider.model_version("en_US-lessac-medium")
    (tmp_path / "en_US-lessac-medium.onnx.json").write_text("{}", encoding="utf-8")
    assert provider.model_version("en_US-lessac-medium") != before


def test_piper_install_rejects_unknown_voices(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="did you mean 'en_US-lessac-medium'"):
        PiperProvider(tmp_path).install("en_US-lessac-medum")


def test_piper_install_downloads_catalog_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fetched: list[str] = []

    def fake_download(file: catalog.RemoteFile, dest: Path, *, show_progress: bool) -> Path:
        fetched.append(file.name)
        (dest / file.name).parent.mkdir(parents=True, exist_ok=True)
        (dest / file.name).write_text("{}", encoding="utf-8")
        return dest / file.name

    monkeypatch.setattr("narratty.tts.piper.download", fake_download)
    provider = PiperProvider(tmp_path)
    provider.install("en_US-amy-medium", show_progress=False)
    assert fetched == ["en_US-amy-medium.onnx", "en_US-amy-medium.onnx.json"]
    assert provider.is_installed("en_US-amy-medium")


def test_piper_missing_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("narratty.tts.piper.find_piper", lambda: None)
    provider = PiperProvider(tmp_path)
    assert provider.unavailable_reason() is not None
    with pytest.raises(MissingDependencyError):
        provider.synthesize("Hi.", "en_US-lessac-medium", tmp_path / "x.wav", {})


class FakeKokoro:
    def __init__(self, model: Path, voices: Path) -> None:
        self.paths = (model, voices)
        self.calls: list[tuple[str, str, float, str]] = []

    def create(self, text: str, voice: str, speed: float, lang: str) -> tuple[list[float], int]:
        self.calls.append((text, voice, speed, lang))
        return [0.1] * 12000, 24000

    def get_voices(self) -> list[str]:
        return ["af_heart", "zf_xiaobei"]


def _install_kokoro(model_dir: Path) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    for file in catalog.kokoro_files():
        (model_dir / file.name).write_bytes(b"x")


def test_kokoro_synthesizes_with_the_voice_language(tmp_path: Path) -> None:
    _install_kokoro(tmp_path)
    engines: list[FakeKokoro] = []

    def factory(model: Path, voices: Path) -> FakeKokoro:
        engines.append(FakeKokoro(model, voices))
        return engines[-1]

    provider = KokoroProvider(tmp_path, engine_factory=factory)
    out = tmp_path / "clip.wav"
    provider.synthesize("Cheerio.", "bf_emma", out, {"speed": 1.1, "lang": None})
    provider.synthesize("Howdy.", "af_heart", tmp_path / "b.wav", {"speed": 1.0, "lang": "en-gb"})
    assert len(engines) == 1, "the model is loaded once"
    assert engines[0].calls == [("Cheerio.", "bf_emma", 1.1, "en-gb"), ("Howdy.", "af_heart", 1.0, "en-gb")]
    assert wav_duration_ms(out) == 500


def test_kokoro_installation_state(tmp_path: Path) -> None:
    provider = KokoroProvider(tmp_path, engine_factory=FakeKokoro)
    assert not provider.is_installed("af_heart")
    _install_kokoro(tmp_path)
    assert provider.is_installed("af_heart")
    assert provider.is_installed("zf_xiaobei"), "voices of the voice pack beyond the curated list"
    assert not provider.is_installed("zz_nobody")


def test_kokoro_without_kokoro_onnx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    provider = KokoroProvider(tmp_path)
    assert "kokoro-onnx is not installed" in (provider.unavailable_reason() or "")
    _install_kokoro(tmp_path)
    with pytest.raises(MissingDependencyError):
        provider.synthesize("Hi.", "af_heart", tmp_path / "x.wav", {})
