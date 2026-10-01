"""VHS, ffprobe and ffmpeg invocations (with a fake runner)."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from narratty.errors import MissingDependencyError, RenderError
from narratty.render import media
from narratty.render.overlays import OverlayImage


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


def test_run_vhs_uses_the_workspace_and_reports_errors(tmp_path: Path) -> None:
    runner = FakeRunner()
    media.run_vhs(tmp_path / "t.tape", tmp_path, runner=runner)
    argv, kwargs = runner.calls[0]
    assert argv == ["/usr/bin/vhs", str(tmp_path / "t.tape")]
    assert kwargs["cwd"] == tmp_path
    with pytest.raises(RenderError, match="chromium crashed"):
        media.run_vhs(
            tmp_path / "t.tape", tmp_path, runner=FakeRunner(returncode=1, stderr="chromium crashed")
        )


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
    assert argv[argv.index("-filter_complex") + 1].startswith("[0:v]subtitles=subtitles.srt:force_style=")
    assert argv[argv.index("-c:v") + 1] == "libx264"
    assert argv[argv.index("-preset") + 1] == "ultrafast"
    assert "-c:s" not in argv
    assert kwargs["cwd"] == tmp_path


def test_mux_with_overlays_reencodes(tmp_path: Path) -> None:
    runner = FakeRunner(stdout='{"format": {"duration": "4.0"}, "streams": []}')
    overlay = OverlayImage(tmp_path / "o.png", "10", "10", 500, 1500)
    media.mux(Path("v.mp4"), Path("a.wav"), tmp_path / "o.mp4", overlays=[overlay], runner=runner)
    argv = runner.calls[-1][0]
    assert argv[argv.index("-loop") + 1 : argv.index("-loop") + 6] == [
        "1",
        "-t",
        "1.500",
        "-i",
        str(overlay.path),
    ]
    assert argv[argv.index("-map") + 1] == "[vo0]"
    assert argv[argv.index("-c:v") + 1] == "libx264"
    assert "-shortest" not in argv
