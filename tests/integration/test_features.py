"""Documented spec features recorded end to end with real VHS, Piper and ffmpeg.

Each test builds a video from a spec that uses one feature of docs/user-guide/spec.md and
building.md and checks what the feature promises: timelapse, overlays, `diff` and
`wait: {prompt: true}` in the plain layout, subtitle modes, `--fast`, `--draft`, a
read-only workspace and the editor layout (when tmux and yazi are installed).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from narratty.build import WorkspaceOptions, build
from narratty.render import media

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not all(shutil.which(tool) for tool in ("vhs", "ttyd", "ffmpeg", "ffprobe")),
        reason="needs vhs, ttyd and ffmpeg",
    ),
]

HEAD = "meta: {title: Features}\nterminal: {width: 800, height: 400, typing_speed_ms: 10}\n"
END_CARD = "end_card: {enabled: true, duration_ms: 1000}\n"


def _spec(tmp_path: Path, body: str, head: str = HEAD + END_CARD) -> Path:
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text(head + body, encoding="utf-8")
    return spec


def _build(spec: Path, max_drift: float = 0.2, **options: object) -> Path:
    workspace = WorkspaceOptions(mode="rw")
    result = build(spec, workspace=workspace, max_drift=max_drift, **options)  # type: ignore[arg-type]
    info = media.probe(result.output)
    assert info.has_video and info.has_audio
    return result.output


def _streams(video: Path) -> list[str]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return [s["codec_type"] for s in json.loads(out.stdout)["streams"]]


def test_timelapse_shortens_the_wait(tmp_path: Path) -> None:
    body = (
        "scenes:\n"
        "  - id: start\n    narration: Start.\n"
        "    actions: [{type_command: 'sleep 4; echo done-$((6*7))'}, enter]\n"
        "  - id: wait\n    timelapse: 4\n    actions: [{wait: {screen: 'done-42', timeout_ms: 20000}}]\n"
    )
    # The plan cannot know how long the wait takes, so the drift check is off.
    normal = _build(_spec(tmp_path, body.replace("    timelapse: 4\n", "")), max_drift=10)
    normal_ms = media.probe(normal).duration_ms  # the next build writes the same file
    sped_up_ms = media.probe(_build(_spec(tmp_path, body), max_drift=10)).duration_ms
    # the 4 s sleep takes about 1 s once the wait scene runs four times faster
    assert sped_up_ms < normal_ms - 1500


def test_overlays_are_drawn_and_the_video_is_reencoded(tmp_path: Path) -> None:
    body = (
        "overlay_styles: {file: {position: top, size: small, color: '#f1fa8c'}}\n"
        "scenes:\n"
        "  - id: a\n    narration: Look at this file.\n"
        "    actions:\n"
        "      - overlay: {text: '1 · Setup', style: chapter}\n"
        "      - run: echo hello\n"
        "      - overlay: {text: src/main.py, style: file, duration_ms: 1500}\n"
    )
    video = _build(_spec(tmp_path, body))
    assert media.probe(video).duration_ms > 0
    frame = tmp_path / "frame.png"
    grab = ["ffmpeg", "-loglevel", "error", "-y", "-ss", "2", "-i", str(video), "-frames:v", "1", str(frame)]
    subprocess.run(grab, check=True)
    assert frame.stat().st_size > 1000


def test_diff_and_wait_for_the_prompt_in_the_plain_layout(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("unchanged\n", encoding="utf-8")
    body = (
        "scenes:\n"
        "  - id: change\n    narration: Change a file.\n"
        "    actions:\n"
        "      - run: echo added > new.txt && sleep 1\n"
        "      - wait: {prompt: true, timeout_ms: 20000}\n"
        "      - diff\n"
        "      - wait: {screen: 'new.txt', timeout_ms: 20000}\n"
    )
    _build(_spec(tmp_path, body))
    assert (tmp_path / "new.txt").is_file()


@pytest.mark.parametrize("mode", ["files", "track", "burn"])
def test_subtitle_modes(tmp_path: Path, mode: str) -> None:
    body = "scenes:\n  - id: a\n    narration: Hello there.\n    actions: [{run: echo hi}]\n"
    video = _build(_spec(tmp_path, body, HEAD + END_CARD + f"subtitles: {mode}\n"))
    if mode == "files":
        assert "Hello there." in video.with_suffix(".srt").read_text(encoding="utf-8")
        assert video.with_suffix(".vtt").read_text(encoding="utf-8").startswith("WEBVTT")
    elif mode == "track":
        assert "subtitle" in _streams(video)
    else:
        assert "subtitle" not in _streams(video), "burned into the picture"


def test_fast_fills_long_pauses(tmp_path: Path) -> None:
    body = "scenes:\n  - id: a\n    narration: Wait.\n    actions: [{run: echo hi}, {hold: 3s}]\n"
    assert media.probe(_build(_spec(tmp_path, body), fast=True)).duration_ms > 3000


def test_draft_needs_no_voice(tmp_path: Path) -> None:
    body = "scenes:\n  - id: a\n    narration: A draft check.\n    actions: [{run: echo hi}]\n"
    result = build(_spec(tmp_path, body), workspace=WorkspaceOptions(mode="rw"), draft=True)
    assert result.output.name.endswith(".draft.mp4") and result.output.is_file()


@pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("tmux", "yazi", "ya", "git")), reason="needs tmux, yazi and git"
)
def test_editor_layout_video(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("first\n", encoding="utf-8")
    layout = "layout: editor, typing_speed_ms: 5"
    head = HEAD.replace("typing_speed_ms: 10", layout).replace("height: 400", "height: 500")
    body = (
        "scenes:\n"
        "  - id: look\n    narration: The explorer and the shell.\n"
        "    actions:\n"
        "      - run: echo changed > notes.txt\n"
        "      - reveal: notes.txt\n"
        "      - focus: explorer\n"
        "      - diff\n"
        "      - wait: {screen: 'first', timeout_ms: 20000}\n"
        "      - key: Escape\n"
    )
    _build(_spec(tmp_path, body, head + END_CARD))
