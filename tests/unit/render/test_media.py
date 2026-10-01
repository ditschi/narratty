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
    assert argv[argv.index("-vf") + 1].startswith("subtitles=subtitles.srt:force_style=")
    assert argv[argv.index("-c:v") + 1] == "libx264"
    assert argv[argv.index("-preset") + 1] == "ultrafast"
    assert "-c:s" not in argv
    assert kwargs["cwd"] == tmp_path


def test_probe_reads_the_frame_rate() -> None:
    payload = {
        "streams": [{"codec_type": "video", "r_frame_rate": "30000/1001"}],
        "format": {"duration": "1.0"},
    }
    info = media.probe(Path("x.mp4"), runner=FakeRunner(stdout=json.dumps(payload)))
    assert info.frame_rate == pytest.approx(29.97, abs=0.01)


def test_freezes_parses_freezedetect() -> None:
    stdout = (
        "frame:0 pts:0 pts_time:0\n"
        "lavfi.freezedetect.freeze_start=0.5\nlavfi.freezedetect.freeze_duration=1\n"
        "lavfi.freezedetect.freeze_end=1.5\n"
        "lavfi.freezedetect.freeze_start=2.04\n"
    )
    runner = FakeRunner(stdout=stdout)
    assert media.freezes(Path("v.mp4"), runner=runner) == [(500, 1500), (2040, None)]
    assert any("freezedetect" in arg for arg in runner.calls[0][0])
    with pytest.raises(RenderError, match="analyse"):
        media.freezes(Path("v.mp4"), runner=FakeRunner(returncode=1))


def test_repeat_frames_shifts_later_inserts(tmp_path: Path) -> None:
    runner = FakeRunner()
    media.repeat_frames(Path("v.mp4"), [(10, 50), (20, 0), (30, 25)], tmp_path / "o.mp4", runner=runner)
    argv = runner.calls[0][0]
    graph = argv[argv.index("-vf") + 1]
    assert graph == "loop=loop=50:size=1:start=10,loop=loop=25:size=1:start=80,setpts=N/FRAME_RATE/TB"
    with pytest.raises(RenderError, match="fill the pauses"):
        media.repeat_frames(Path("v.mp4"), [], tmp_path / "o.mp4", runner=FakeRunner(returncode=1))


FAKE_VHS = """\
#!/bin/sh
printf '\\033[90mFile: t.tape\\033[0m\\n\\n'
printf '\\033[94mHide\\033[0m \\n'
printf 'Sleep 10ms\\n'
[ -n "$FAIL" ] && { echo "recording failed"; exit 1; }
printf 'Creating v.mp4...\\n'
"""


def test_run_vhs_timed_stamps_each_progress_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vhs = tmp_path / "vhs"
    vhs.write_text(FAKE_VHS, encoding="utf-8")
    vhs.chmod(0o755)
    monkeypatch.setattr(media.shutil, "which", lambda name: str(vhs))
    seen: list[int] = []
    ticks = iter(range(100))
    lines = media.run_vhs_timed(
        tmp_path / "t.tape",
        tmp_path,
        on_line=lambda index, pid: seen.append(index),
        clock=lambda: next(ticks),
    )
    assert lines == [(0, "Hide"), (1, "Sleep 10ms"), (2, "Creating v.mp4...")]
    assert seen == [0, 1, 2]
    monkeypatch.setenv("FAIL", "1")
    with pytest.raises(RenderError, match="recording failed"):
        media.run_vhs_timed(tmp_path / "t.tape", tmp_path)
