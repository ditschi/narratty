"""voices, tts and cache commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from narratty.cli.app import app
from narratty.cli.commands.cache import parse_age
from narratty.cli.completion import complete_provider, complete_voice
from narratty.errors import MissingDependencyError, UsageError, ValidationError
from narratty.tts import catalog
from tests.helpers import plain, write_tone

runner = CliRunner()


def _install_piper_voice(data: Path) -> None:
    voice_dir = data / "piper"
    voice_dir.mkdir(parents=True)
    (voice_dir / "en_US-lessac-medium.onnx").write_bytes(b"onnx")
    (voice_dir / "en_US-lessac-medium.onnx.json").write_text("{}", encoding="utf-8")


def test_voices_lists_both_providers(tmp_path: Path) -> None:
    result = runner.invoke(app, ["voices"])
    assert result.exit_code == 0, result.output
    text = plain(result.output)
    assert "en_US-lessac-medium" in text and "af_heart" in text


def test_voices_installed_filter(tmp_path: Path) -> None:
    _install_piper_voice(tmp_path / "data")
    result = runner.invoke(app, ["voices", "--installed", "-p", "piper"], env={"COLUMNS": "200"})
    text = plain(result.output)
    assert "en_US-lessac-medium" in text
    assert "en_US-amy-medium" not in text


def test_voices_pull_skips_installed_voice(tmp_path: Path) -> None:
    _install_piper_voice(tmp_path / "data")
    result = runner.invoke(app, ["voices", "pull", "en_US-lessac-medium"])
    assert result.exit_code == 0
    assert "already installed" in plain(result.output)


def test_voices_pull_guesses_kokoro(monkeypatch: pytest.MonkeyPatch) -> None:
    pulled: list[str] = []
    monkeypatch.setattr("narratty.tts.kokoro.KokoroProvider.is_installed", lambda self, voice: False)
    monkeypatch.setattr(
        "narratty.tts.kokoro.KokoroProvider.install", lambda self, voice, **_: pulled.append(voice)
    )
    result = runner.invoke(app, ["voices", "pull", "af_heart"])
    assert result.exit_code == 0, result.output
    assert pulled == ["af_heart"]


def test_validate_rejects_unknown_voice(tmp_path: Path) -> None:
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text("tts:\n  voice: en_US-lessac-medum\nscenes:\n  - id: a\n", encoding="utf-8")
    result = runner.invoke(app, ["validate", str(spec)])
    assert isinstance(result.exception, ValidationError)
    assert "did you mean 'en_US-lessac-medium'" in result.exception.message


def test_tts_offline_without_voice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("narratty.tts.piper.find_piper", lambda: ["piper"])
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text("scenes:\n  - id: a\n    narration: Hi.\n", encoding="utf-8")
    result = runner.invoke(app, ["tts", str(spec), "--offline"])
    assert isinstance(result.exception, MissingDependencyError)


def test_tts_prints_clip_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_piper_voice(tmp_path / "data")

    def fake_synthesize(self: object, text: str, voice: str, out: Path, options: object) -> None:
        write_tone(out, 750)

    monkeypatch.setattr("narratty.tts.piper.find_piper", lambda: ["piper"])
    monkeypatch.setattr("narratty.tts.piper.PiperProvider.synthesize", fake_synthesize)
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text("scenes:\n  - id: intro\n    narration: Hi there.\n", encoding="utf-8")
    first = runner.invoke(app, ["tts", str(spec)], env={"COLUMNS": "200"})
    assert first.exit_code == 0, first.output
    assert "intro" in plain(first.output) and "0.75s" in plain(first.output) and "new" in plain(first.output)
    second = runner.invoke(app, ["tts", str(spec)], env={"COLUMNS": "200"})
    assert "hit" in plain(second.output)

    info = runner.invoke(app, ["cache", "info"])
    assert "1 clips" in plain(info.output)
    pruned = runner.invoke(app, ["cache", "prune", "--all"])
    assert "removed 1 clips" in plain(pruned.output)


@pytest.mark.parametrize(
    ("text", "seconds"), [("30d", 30 * 86400), ("12h", 43200), ("90m", 5400), ("2w", 1209600)]
)
def test_parse_age(text: str, seconds: int) -> None:
    assert parse_age(text) == seconds


def test_parse_age_rejects_garbage() -> None:
    with pytest.raises(UsageError):
        parse_age("soon")


def test_provider_and_voice_completion() -> None:
    assert complete_provider("k") == ["kokoro"]

    class Ctx:
        params = {"provider": "kokoro"}

    voices = complete_voice(Ctx(), "af_")  # type: ignore[arg-type]
    assert voices and all(v.startswith("af_") for v in voices)
    assert set(voices) <= set(catalog.voice_ids("kokoro"))
