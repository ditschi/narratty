"""Overlays muxed by a real ffmpeg appear only while they are shown."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from narratty.render import media
from narratty.render.overlays import OverlayImage

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not all(shutil.which(tool) for tool in ("ffmpeg", "ffprobe")), reason="needs ffmpeg"),
]

SIZE = 64


def _ffmpeg(*args: str) -> bytes:
    return subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, capture_output=True).stdout


def _pixel(video: Path, seconds: float) -> tuple[int, ...]:
    """The colour in the middle of the frame at ``seconds``."""
    raw = _ffmpeg(
        "-ss", f"{seconds}", "-i", str(video), "-frames:v", "1",
        "-vf", f"crop=2:2:{SIZE // 2}:{SIZE // 2}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    )  # fmt: skip
    return tuple(raw[:3])


def test_an_overlay_shows_only_in_its_interval(tmp_path: Path) -> None:
    video, audio, out = tmp_path / "silent.mp4", tmp_path / "voice.wav", tmp_path / "out.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", f"color=c=black:s={SIZE}x{SIZE}:r=25:d=6",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
    )  # fmt: skip
    _ffmpeg("-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "6", str(audio))
    png = tmp_path / "overlay.png"
    Image.new("RGBA", (SIZE, SIZE), (255, 255, 255, 255)).save(png)

    media.mux(video, audio, out, overlays=[OverlayImage(png, "0", "0", 2000, 4000)])

    assert media.probe(out).duration_ms == pytest.approx(6000, abs=100)
    before, during, after = (_pixel(out, seconds) for seconds in (1, 3, 5))
    assert max(before) < 40, before
    assert min(during) > 215, during
    assert max(after) < 40, after


def test_the_frame_band_has_the_terminals_background(tmp_path: Path) -> None:
    video, audio, out = tmp_path / "silent.mp4", tmp_path / "voice.wav", tmp_path / "out.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", f"color=c=0x3060c0:s={SIZE}x{SIZE}:r=25:d=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
    )  # fmt: skip
    _ffmpeg("-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "2", str(audio))

    media.mux(video, audio, out, band=16)

    size = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(out)],
        check=True, capture_output=True, text=True,
    ).stdout.split()[0]  # fmt: skip
    assert size == f"{SIZE},{SIZE + 16}"
    raw = _ffmpeg(
        "-ss",
        "1",
        "-i",
        str(out),
        "-frames:v",
        "1",
        "-vf",
        "crop=2:2:30:6",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-",
    )
    assert all(abs(a - b) < 24 for a, b in zip(raw[:3], (0x30, 0x60, 0xC0), strict=True)), tuple(raw[:3])
