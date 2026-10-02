"""plan, tape, render and build commands with TTS and media faked."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from narratty.build import BuildResult
from narratty.cli.app import app
from narratty.errors import SyncError, UsageError
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


def test_build_cast_writes_page_cast_and_audio(spec: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_mp3(audio: Path, out: Path) -> None:
        out.write_bytes(b"ID3")

    monkeypatch.setattr("narratty.render.media.encode_mp3", fake_mp3)
    result = runner.invoke(app, ["build", str(spec), "--format", "cast", "--no-end-card"])
    assert result.exit_code == 0, result.output
    assert "cast " in plain(result.output)
    page, cast = spec.with_name("demo.html"), spec.with_name("demo.cast")
    assert spec.with_name("demo.mp3").read_bytes() == b"ID3"
    assert '"m", "intro"' in cast.read_text(encoding="utf-8")
    assert "data:audio/mpeg;base64,SUQz" in page.read_text(encoding="utf-8")


def test_build_cast_in_a_container(spec: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_delegate(command: str, spec_path: Path, **kwargs: object) -> int:
        calls.append(kwargs)
        return 0

    monkeypatch.setattr("narratty.container.delegate", fake_delegate)
    result = runner.invoke(app, ["build", str(spec), "-f", "cast", "--runtime", "docker"])
    assert result.exit_code == 0, result.output
    assert calls[0]["output"] == spec.with_name("demo.html")
    extra = calls[0]["extra_args"]
    assert isinstance(extra, list) and extra[:2] == ["--format", "cast"]


def test_build_sync_failure_exit_code(spec: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_build(*args: object, **kwargs: object) -> BuildResult:
        raise SyncError("drifted")

    monkeypatch.setattr("narratty.build.build", failing_build)
    result = runner.invoke(app, ["build", str(spec)])
    assert isinstance(result.exception, SyncError)


def test_env_shell_needs_an_environment(tmp_path: Path) -> None:
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text("scenes: [{id: a}]\n", encoding="utf-8")
    result = CliRunner().invoke(app, ["env", "shell", str(spec)])
    assert "has no environment" in str(result.exception)


def test_plan_draft_estimates_without_tts(spec: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("narratty.build.get_provider", lambda *args: pytest.fail("TTS loaded"))
    result = runner.invoke(app, ["plan", str(spec), "--draft"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    assert "(estimated)" in plain(result.output)


def test_build_draft_passes_its_options(spec: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_build(spec_path: Path, output: Path | None, **kwargs: object) -> BuildResult:
        assert kwargs["draft"] is True
        assert kwargs["subtitles"] == "track"
        return BuildResult(spec_path.with_name("demo.draft.mp4"), 10000, 10000, ())

    monkeypatch.setattr("narratty.build.build", fake_build)
    result = runner.invoke(app, ["build", str(spec), "--draft", "--subtitles", "track"])
    assert result.exit_code == 0, result.output


def test_build_draft_in_a_container(spec: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_delegate(command: str, spec_path: Path, **kwargs: object) -> int:
        calls.append(kwargs)
        return 0

    monkeypatch.setattr("narratty.container.delegate", fake_delegate)
    result = runner.invoke(
        app, ["build", str(spec), "--draft", "--subtitles", "files", "--runtime", "docker"]
    )
    assert result.exit_code == 0, result.output
    assert calls[0]["output"] == spec.with_name("demo.draft.mp4")
    extra = calls[0]["extra_args"]
    assert isinstance(extra, list) and extra[-3:] == ["--subtitles", "files", "--draft"]


def test_build_draft_needs_mp4(spec: Path) -> None:
    result = runner.invoke(app, ["build", str(spec), "--draft", "--format", "cast"])
    assert isinstance(result.exception, UsageError)


def test_build_cast_writes_subtitle_files(spec: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("narratty.render.media.encode_mp3", lambda audio, out: out.write_bytes(b"ID3"))
    result = runner.invoke(app, ["build", str(spec), "-f", "cast", "--no-end-card", "--subtitles", "burn"])
    assert result.exit_code == 0, result.output
    assert "Hello there my friend." in spec.with_name("demo.vtt").read_text(encoding="utf-8")


def test_plan_says_what_the_next_build_records(spec: Path) -> None:
    text = plain(runner.invoke(app, ["plan", str(spec), "--draft"], env={"COLUMNS": "200"}).output)
    assert "recording" in text and "record" in text and "cached" not in text


def test_build_passes_scenes_and_clean(spec: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_build(spec_path: Path, output: Path | None, **kwargs: object) -> BuildResult:
        seen.update(kwargs, output=output)
        return BuildResult(spec_path.with_name("demo.scenes.mp4"), 10000, 10000, ())

    monkeypatch.setattr("narratty.build.build", fake_build)
    result = runner.invoke(app, ["build", str(spec), "--scenes", "intro", "-s", "a:b,c", "--clean"])
    assert result.exit_code == 0, result.output
    assert seen["scenes"] == ["intro", "a:b,c"] and seen["clean"] is True
    assert seen["output"] == spec.with_name("demo.scenes.mp4")


def test_build_scenes_and_clean_reach_the_container(spec: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_delegate(command: str, spec_path: Path, **kwargs: object) -> int:
        calls.append(kwargs)
        return 0

    monkeypatch.setattr("narratty.container.delegate", fake_delegate)
    result = runner.invoke(
        app, ["build", str(spec), "--draft", "--clean", "--scenes", "intro", "--runtime", "docker"]
    )
    assert result.exit_code == 0, result.output
    assert calls[0]["output"] == spec.with_name("demo.scenes.draft.mp4")
    extra = calls[0]["extra_args"]
    assert isinstance(extra, list) and extra[-3:] == ["--clean", "--scenes", "intro"]


def test_build_watch_runs_the_watch_loop(spec: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    builds: list[Path] = []

    def fake_watch(spec_path: Path, build: object, **kwargs: object) -> None:
        assert callable(build)
        builds.append(spec_path)
        build()

    def fake_build(spec_path: Path, output: Path | None, **kwargs: object) -> BuildResult:
        return BuildResult(spec_path.with_name("demo.mp4"), 10000, 10000, ())

    monkeypatch.setattr("narratty.watch.watch", fake_watch)
    monkeypatch.setattr("narratty.build.build", fake_build)
    result = runner.invoke(app, ["build", str(spec), "--watch"])
    assert result.exit_code == 0, result.output
    assert builds == [spec]


def test_build_cast_scenes_records_only_those(spec: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("narratty.render.media.encode_mp3", lambda audio, out: out.write_bytes(b"ID3"))
    result = runner.invoke(app, ["build", str(spec), "-f", "cast", "--no-end-card", "--scenes", "intro"])
    assert result.exit_code == 0, result.output
    cast = spec.with_name("demo.scenes.cast").read_text(encoding="utf-8")
    assert '"m", "intro"' in cast
    assert spec.with_name("demo.scenes.html").is_file()


def test_build_unknown_scene_is_a_usage_error(spec: Path) -> None:
    result = runner.invoke(app, ["build", str(spec), "--scenes", "intor"])
    assert isinstance(result.exception, UsageError) and "intro" in (result.exception.hint or "")
