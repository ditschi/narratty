"""plan, tape, render and build commands with TTS and media faked."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from narratty.build import BuildResult
from narratty.cli.app import app
from narratty.errors import SyncError
from narratty.tts.base import TtsProvider
from tests.helpers import plain
from tests.unit.tts.test_synth import ToneProvider

runner = CliRunner()

SPEC = """\
scenes:
  - id: setup
    hidden: true
    actions: [{type_command: "cd /tmp"}, enter]
  - id: intro
    narration: Hello there my friend.
    actions: [{type_command: ls}, enter]
"""


@pytest.fixture
def spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    def fake_provider(name: str, data: Path) -> TtsProvider:
        return ToneProvider()

    monkeypatch.setattr("narratty.build.get_provider", fake_provider)
    path = tmp_path / "demo.narratty.yaml"
    path.write_text(SPEC, encoding="utf-8")
    return path


def test_plan_prints_the_timeline(spec: Path) -> None:
    result = runner.invoke(app, ["plan", str(spec)], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    text = plain(result.output)
    assert "setup (hidden)" in text
    assert "intro" in text and "0.40s" in text  # four words of tone
    assert "end card" in text and "4.00s" in text
    assert "total: 6.20s" in text  # 300 lead-in + 400 + 500 buffer + 1000 tail + 4000 end card


def test_plan_without_end_card(spec: Path) -> None:
    result = runner.invoke(app, ["plan", str(spec), "--no-end-card"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    text = plain(result.output)
    assert "end card" not in text
    assert "total: 2.20s" in text


def test_tape_draws_the_end_card(spec: Path) -> None:
    result = runner.invoke(app, ["tape", str(spec)])
    assert result.exit_code == 0, result.output
    assert "# end card" in result.output
    assert "-m narratty.end_card" in result.output
    result = runner.invoke(app, ["tape", str(spec), "--no-end-card"])
    assert "# end card" not in result.output


def test_config_turns_the_end_card_off(spec: Path, tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.toml").write_text("[end_card]\nenabled = false\n", encoding="utf-8")
    assert "# end card" not in runner.invoke(app, ["tape", str(spec)]).output
    assert "# end card" in runner.invoke(app, ["tape", str(spec), "--end-card"]).output


def test_tape_prints_vhs_commands(spec: Path) -> None:
    result = runner.invoke(app, ["tape", str(spec), "-o", "/x/out.mp4"])
    assert result.exit_code == 0, result.output
    assert 'Output "/x/out.mp4"' in result.output
    assert "# scene: intro" in result.output


def test_render_writes_the_silent_video(spec: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_vhs(tape: Path, cwd: Path, **_: object) -> None:
        assert cwd != spec.parent.resolve(), "runs in a snapshot by default"
        assert (cwd / "demo.narratty.yaml").is_file()
        (spec.parent / "demo.silent.mp4").write_bytes(b"mp4")

    monkeypatch.setattr("narratty.render.media.run_vhs", fake_vhs)
    result = runner.invoke(app, ["render", str(spec)])
    assert result.exit_code == 0, result.output
    assert (spec.parent / "demo.silent.mp4").read_bytes() == b"mp4"


def test_build_reports_drift(spec: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_build(spec_path: Path, output: Path | None, **kwargs: object) -> BuildResult:
        assert kwargs["max_drift"] == 0.05
        return BuildResult(spec_path.with_suffix(".mp4"), 10000, 9800, ())

    monkeypatch.setattr("narratty.build.build", fake_build)
    result = runner.invoke(app, ["build", str(spec), "--max-drift", "0.05"])
    assert result.exit_code == 0, result.output
    assert "-2.0%" in plain(result.output)


def test_build_sync_failure_exit_code(spec: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_build(*args: object, **kwargs: object) -> BuildResult:
        raise SyncError("drifted")

    monkeypatch.setattr("narratty.build.build", failing_build)
    result = runner.invoke(app, ["build", str(spec)])
    assert isinstance(result.exception, SyncError)
