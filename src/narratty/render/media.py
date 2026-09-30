"""External media tools: VHS for the silent video, ffmpeg/ffprobe for audio and muxing."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from narratty.errors import MissingDependencyError, RenderError

Runner = Callable[..., subprocess.CompletedProcess[str]]


def _run(
    argv: Sequence[str], *, cwd: Path | None = None, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), cwd=cwd, env=env, capture_output=True, text=True, check=False)  # noqa: S603


def require(tool: str) -> str:
    """Absolute path of ``tool`` on PATH, or a missing-dependency error."""
    path = shutil.which(tool)
    if path is None:
        raise MissingDependencyError(
            f"{tool} is not installed",
            hint="`narratty doctor --runtime native` lists what to install, or use --runtime docker.",
        )
    return path


def _tail(result: subprocess.CompletedProcess[str], lines: int = 5) -> str:
    output = (result.stderr or result.stdout or "").strip().splitlines()
    return "\n".join(output[-lines:]) or "no output"


def vhs_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Environment for VHS; Chromium's sandbox cannot run as root or in containers."""
    env = dict(os.environ if base is None else base)
    if (hasattr(os, "geteuid") and os.geteuid() == 0) or env.get("NARRATTY_IN_CONTAINER"):
        env.setdefault("VHS_NO_SANDBOX", "true")
    return env


def run_vhs(
    tape: Path, cwd: Path, *, extra_env: Mapping[str, str] | None = None, runner: Runner = _run
) -> None:
    """Render ``tape`` with VHS, running the recorded shell in ``cwd``."""
    env = {**vhs_env(), **(extra_env or {})}
    result = runner([require("vhs"), str(tape)], cwd=cwd, env=env)
    if result.returncode != 0:
        raise RenderError(
            f"VHS failed:\n{_tail(result)}", hint=f"The tape is at {tape}; run `vhs {tape}` to debug."
        )


@dataclass(frozen=True)
class MediaInfo:
    """What ffprobe reports about a media file."""

    duration_ms: int
    has_video: bool
    has_audio: bool


def probe(path: Path, *, runner: Runner = _run) -> MediaInfo:
    """Duration and stream types of ``path``."""
    argv = [
        require("ffprobe"),
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type",
        "-of",
        "json",
        str(path),
    ]
    result = runner(argv)
    if result.returncode != 0:
        raise RenderError(f"ffprobe could not read {path}:\n{_tail(result)}")
    data = json.loads(result.stdout)
    kinds = {stream.get("codec_type") for stream in data.get("streams", [])}
    duration = float(data.get("format", {}).get("duration", 0.0))
    return MediaInfo(round(duration * 1000), "video" in kinds, "audio" in kinds)


# Opaque box behind the text; sizes are in libass's 384x288 script coordinates.
BURN_STYLE = (
    "FontName=DejaVu Sans,FontSize=14,BorderStyle=3,OutlineColour=&H80000000,Outline=2,Shadow=0,MarginV=12"
)


def mux(
    video: Path,
    audio: Path,
    out: Path,
    *,
    subtitles: Path | None = None,
    burn: bool = False,
    fast: bool = False,
    runner: Runner = _run,
) -> None:
    """Combine the silent video with the narration track (AAC).

    ``subtitles`` (an SRT) becomes a soft subtitle track, or with ``burn`` is drawn
    into the picture. ``fast`` (drafts) scales the picture to half size and encodes it
    quickly. Either re-encodes the video; otherwise the video stream is copied as is.
    ffmpeg runs in the SRT's directory so the filter graph only sees its plain file name.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    argv = [require("ffmpeg"), "-y", "-v", "error", "-i", str(video), "-i", str(audio)]
    maps = ["-map", "0:v:0", "-map", "1:a:0"]
    # -shortest would also stop at the last subtitle, so a soft track ends at the video instead.
    length = ["-shortest"]
    filters = []
    if subtitles is not None and burn:
        filters.append(f"subtitles={subtitles.name}:force_style='{BURN_STYLE}'")
    if fast:
        # After the subtitles, so they are drawn at full resolution.
        filters.append("scale=trunc(iw/4)*2:trunc(ih/4)*2")
    if filters:
        video_codec = [
            "-vf", ",".join(filters),
            "-c:v", "libx264", "-preset", "ultrafast" if fast else "medium",
            "-crf", "28" if fast else "18", "-pix_fmt", "yuv420p",
        ]  # fmt: skip
    else:
        video_codec = ["-c:v", "copy"]
    if subtitles is not None and not burn:
        argv += ["-i", str(subtitles)]
        maps += ["-map", "2:s:0"]
        video_codec += ["-c:s", "mov_text"]
        length = ["-t", f"{probe(video, runner=runner).duration_ms / 1000:.3f}"]
    argv += [
        *maps, *video_codec,
        "-c:a", "aac", "-b:a", "160k",
        *length, "-movflags", "+faststart",
        str(out),
    ]  # fmt: skip
    result = runner(argv, cwd=subtitles.parent) if subtitles is not None else runner(argv)
    if result.returncode != 0:
        raise RenderError(f"ffmpeg failed to mux {out}:\n{_tail(result)}")


def encode_mp3(audio: Path, out: Path, *, runner: Runner = _run) -> None:
    """Encode ``audio`` as a mono MP3 (64 kbit/s, plenty for speech)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        require("ffmpeg"), "-y", "-v", "error", "-i", str(audio),
        "-ac", "1", "-c:a", "libmp3lame", "-b:a", "64k", str(out),
    ]  # fmt: skip
    result = runner(argv)
    if result.returncode != 0:
        raise RenderError(f"ffmpeg failed to encode {out}:\n{_tail(result)}")
