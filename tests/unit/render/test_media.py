"""VHS, ffprobe and ffmpeg invocations (with a fake runner)."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from narratty.errors import MissingDependencyError, RenderError
from narratty.render import media


class FakeRunner:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self.result = (returncode, stdout, stderr)

    def __call__(self, argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), kwargs))
        code, out, err = self.result
        return subprocess.CompletedProcess(list(argv), code, out, err)


@pytest.fixture(autouse=True)
def _tools_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(media.shutil, "which", lambda name: f"/usr/bin/{name}")


def test_probe_parses_ffprobe_json() -> None:
    payload = {
        "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
        "format": {"duration": "12.3456"},
    }
    runner = FakeRunner(stdout=json.dumps(payload))
    info = media.probe(Path("x.mp4"), runner=runner)
    assert info == media.MediaInfo(12346, True, True)
    assert runner.calls[0][0][0] == "/usr/bin/ffprobe"


def test_probe_failure() -> None:
    with pytest.raises(RenderError, match="could not read"):
        media.probe(Path("x.mp4"), runner=FakeRunner(returncode=1, stderr="moov atom not found"))


def test_mux_copies_video_and_encodes_aac(tmp_path: Path) -> None:
    runner = FakeRunner()
    media.mux(Path("v.mp4"), Path("a.wav"), tmp_path / "out" / "o.mp4", runner=runner)
    argv = runner.calls[0][0]
    assert argv[argv.index("-c:v") + 1] == "copy"
    assert argv[argv.index("-c:a") + 1] == "aac"
    assert argv[-1] == str(tmp_path / "out" / "o.mp4")
    assert (tmp_path / "out").is_dir()


def test_encode_mp3(tmp_path: Path) -> None:
    runner = FakeRunner()
    media.encode_mp3(Path("a.wav"), tmp_path / "out" / "a.mp3", runner=runner)
    argv = runner.calls[0][0]
    assert argv[argv.index("-c:a") + 1] == "libmp3lame"
    assert argv[-1] == str(tmp_path / "out" / "a.mp3")
    with pytest.raises(RenderError, match="encode"):
        media.encode_mp3(Path("a.wav"), tmp_path / "a.mp3", runner=FakeRunner(returncode=1))


def test_run_vhs_logs_lines_with_times(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(media.shutil, "which", lambda name: f"/usr/bin/{name}")
    calls: list[tuple[list[str], dict[str, object]]] = []
    ticks = iter([10.0, 10.5, 12.0])

    @contextmanager
    def stream(argv: list[str], **kwargs: object) -> Iterator[Iterator[str]]:
        calls.append((argv, kwargs))
        yield iter(["Show\n", "\x1b[1mSleep 1s\x1b[0m\n"])

    log = media.run_vhs(tmp_path / "t.tape", tmp_path, stream=stream, clock=lambda: next(ticks))
    assert log == [media.LogLine(0.5, "Show"), media.LogLine(2.0, "Sleep 1s")]
    argv, kwargs = calls[0]
    assert argv == ["/usr/bin/vhs", str(tmp_path / "t.tape")]
    assert kwargs["cwd"] == tmp_path


def test_run_vhs_reports_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(media.shutil, "which", lambda name: f"/usr/bin/{name}")

    @contextmanager
    def stream(argv: list[str], **_: object) -> Iterator[Iterator[str]]:
        yield iter(["chromium crashed\n"])
        raise subprocess.CalledProcessError(1, argv)

    with pytest.raises(RenderError, match="chromium crashed"):
        media.run_vhs(tmp_path / "t.tape", tmp_path, stream=stream)


def test_run_vhs_streams_a_real_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = tmp_path / "vhs"
    script.write_text("#!/bin/sh\necho Hide\necho Show\nexit $1\n", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setattr(media, "require", lambda tool: str(script))
    assert [line.text for line in media.run_vhs(Path("0"), tmp_path)] == ["Hide", "Show"]
    with pytest.raises(RenderError, match="Show"):
        media.run_vhs(Path("3"), tmp_path)


def test_vhs_env_disables_the_sandbox_in_containers() -> None:
    assert media.vhs_env({"NARRATTY_IN_CONTAINER": "1"})["VHS_NO_SANDBOX"] == "true"
    assert (
        media.vhs_env({"NARRATTY_IN_CONTAINER": "1", "VHS_NO_SANDBOX": "false"})["VHS_NO_SANDBOX"] == "false"
    )


def test_missing_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(media.shutil, "which", lambda name: None)
    with pytest.raises(MissingDependencyError, match="ffmpeg is not installed"):
        media.require("ffmpeg")


def test_mux_adds_a_soft_subtitle_track(tmp_path: Path) -> None:
    runner = FakeRunner(stdout=json.dumps({"streams": [], "format": {"duration": "12.5"}}))
    srt = tmp_path / "subtitles.srt"
    media.mux(Path("v.mp4"), Path("a.wav"), tmp_path / "o.mp4", subtitles=srt, runner=runner)
    argv, kwargs = runner.calls[-1]
    assert argv[argv.index("-c:v") + 1] == "copy"
    assert argv[argv.index("-c:s") + 1] == "mov_text"
    assert "2:s:0" in argv
    assert "-shortest" not in argv, "would cut the video at the last cue"
    assert argv[argv.index("-t") + 1] == "12.500"
    assert kwargs["cwd"] == tmp_path


def test_mux_burns_subtitles_in(tmp_path: Path) -> None:
    runner = FakeRunner()
    srt = tmp_path / "subtitles.srt"
    media.mux(
        Path("v.mp4"), Path("a.wav"), tmp_path / "o.mp4", subtitles=srt, burn=True, fast=True, runner=runner
    )
    argv, kwargs = runner.calls[0]
    subtitles, scale = argv[argv.index("-vf") + 1].rsplit(",", 1)
    assert subtitles.startswith("subtitles=subtitles.srt:force_style=")
    assert scale == "scale=trunc(iw/4)*2:trunc(ih/4)*2", "drafts shrink after drawing the text"
    assert argv[argv.index("-c:v") + 1] == "libx264"
    assert argv[argv.index("-preset") + 1] == "ultrafast"
    assert "-c:s" not in argv
    assert kwargs["cwd"] == tmp_path


def test_draft_mux_without_subtitles_still_shrinks(tmp_path: Path) -> None:
    runner = FakeRunner()
    media.mux(Path("v.mp4"), Path("a.wav"), tmp_path / "o.mp4", fast=True, runner=runner)
    argv = runner.calls[0][0]
    assert argv[argv.index("-vf") + 1] == "scale=trunc(iw/4)*2:trunc(ih/4)*2"
    assert argv[argv.index("-c:v") + 1] == "libx264"
