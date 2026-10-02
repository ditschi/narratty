"""The full pipeline with real Piper, VHS and ffmpeg."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from narratty.build import WorkspaceOptions, build
from narratty.cli.app import app
from narratty.errors import CommandError
from narratty.render import media
from tests.helpers import plain

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not all(shutil.which(tool) for tool in ("vhs", "ttyd", "ffmpeg", "ffprobe")),
        reason="needs vhs, ttyd and ffmpeg",
    ),
]

SPEC = """\
meta: {title: Integration}
terminal: {width: 800, height: 400}
scenes:
  - id: setup
    hidden: true
    actions:
      - type_command: "mkdir -p demo && cd demo && touch one.txt two.txt"
      - enter
  - id: list
    narration: Here are the files in the demo directory.
    actions:
      - type_command: "ls"
      - enter
  - id: quiet
    actions:
      - type_command: "echo \\"it's done\\""
      - enter
      - hold: 700
  - id: wrap
    narration: That is the whole demo.
"""


@pytest.fixture
def spec(tmp_path: Path) -> Path:
    path = tmp_path / "demo.narratty.yaml"
    path.write_text(SPEC, encoding="utf-8")
    return path


def test_build_produces_a_synced_video(spec: Path, tmp_path: Path) -> None:
    result = build(spec, work_dir=tmp_path / "work", workspace=WorkspaceOptions(mode="rw"))
    info = media.probe(result.output)
    assert info.has_video and info.has_audio
    assert abs(result.drift) < 0.05, f"video {result.video_ms} ms vs plan {result.expected_ms} ms"
    assert abs(info.duration_ms - result.video_ms) < 200
    assert [p.scene_id for p in result.placements] == ["list", "wrap"]
    work = tmp_path / "work"
    assert {"scene.tape", "silent.mp4", "narration.wav"} <= {p.name for p in work.iterdir()}
    assert (spec.parent / "demo" / "one.txt").exists(), "rw mode runs in place"


def test_build_command_leaves_the_workspace_alone(spec: Path) -> None:
    result = CliRunner().invoke(app, ["build", str(spec), "-o", str(spec.parent / "out.mp4")])
    assert result.exit_code == 0, result.output
    assert (spec.parent / "out.mp4").is_file()
    assert "planned" in plain(result.output)
    assert not (spec.parent / "demo").exists(), "the default snapshot mode keeps the source untouched"


def _last_frame_white_share(video: Path) -> float:
    frame = subprocess.run(
        ["ffmpeg", "-v", "error", "-sseof", "-1", "-i", str(video), "-frames:v", "1"]
        + ["-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True,
        check=True,
    ).stdout
    return sum(1 for value in frame if value > 200) / len(frame)


def test_end_card_shows_the_qr_code(tmp_path: Path) -> None:
    spec = tmp_path / "card.narratty.yaml"
    spec.write_text(
        "terminal: {width: 1200, height: 700}\n"
        "end_card: {duration_ms: 2000}\n"
        "scenes:\n  - id: hi\n    actions: [{type_command: 'echo hi'}, enter, {hold: 500}]\n",
        encoding="utf-8",
    )
    result = build(spec, end_card=True)
    assert abs(result.drift) < 0.05
    assert _last_frame_white_share(result.output) > 0.1, "the white QR code fills the last frame"
    work = tmp_path / "plain"
    plain_result = build(spec, tmp_path / "plain.mp4", work_dir=work, end_card=False, clean=True)
    assert result.expected_ms - plain_result.expected_ms == 2000
    assert _last_frame_white_share(plain_result.output) < 0.01
    assert "end card" not in (work / "scene.tape").read_text(encoding="utf-8")


EXITS = """\
terminal: {{width: 600, height: 300}}
end_card: false
scenes:
  - id: missing
    narration: This file does not exist.
    expect_exit: {expect}
    actions: [{{type_command: "cat missing.txt"}}, enter]
"""


@pytest.mark.parametrize(("expect", "fails"), [("success", True), ("failure", False), ("any", False)])
def test_build_checks_exit_codes(tmp_path: Path, expect: str, fails: bool) -> None:
    spec = tmp_path / "exits.narratty.yaml"
    spec.write_text(EXITS.format(expect=expect), encoding="utf-8")
    options = WorkspaceOptions(mode="rw")
    if fails:
        with pytest.raises(CommandError, match="`cat missing.txt` exited with 1"):
            build(spec, draft=True, workspace=options)
        assert (tmp_path / "exits.draft.mp4").is_file(), "the video is kept for inspection"
    else:
        build(spec, draft=True, workspace=options)


def test_scenes_come_from_the_cache_and_ranges_replay_earlier_scenes(spec: Path) -> None:
    options = WorkspaceOptions(mode="rw")
    first_log: list[str] = []
    first = build(spec, draft=True, workspace=options, log=first_log.append)
    assert "recording 3 of 3 scenes with VHS" in first_log
    again_log: list[str] = []
    again = build(spec, draft=True, workspace=options, log=again_log.append)
    assert "every scene is cached, nothing to record" in again_log
    assert abs(again.video_ms - first.video_ms) < 100

    ranged_log: list[str] = []
    ranged = build(spec, draft=True, workspace=options, scenes=["quiet:wrap"], log=ranged_log.append)
    assert ranged.output.name == "demo.scenes.draft.mp4"
    assert [p.scene_id for p in ranged.placements] == []  # a draft has no clips
    assert media.probe(ranged.output).duration_ms < first.video_ms
    assert "every scene is cached, nothing to record" in ranged_log

    clean_log: list[str] = []
    build(spec, draft=True, workspace=options, clean=True, scenes=["wrap"], log=clean_log.append)
    assert "recording 1 of 1 scenes with VHS" in clean_log


def test_a_replayed_scene_leaves_its_effects_for_the_recorded_one(spec: Path) -> None:
    options = WorkspaceOptions(mode="rw")
    text = spec.read_text(encoding="utf-8").replace(
        "  - id: wrap\n",
        "  - id: files\n    actions: [{type_command: 'ls | wc -l'}, enter, {hold: 300}]\n  - id: wrap\n",
    )
    spec.write_text(text, encoding="utf-8")
    work = spec.parent / "work"
    build(spec, draft=True, workspace=options, scenes=["files"], work_dir=work)
    tape = (work / "scene.tape").read_text(encoding="utf-8")
    assert "# scene: setup (hidden)" in tape and "# scene: list (hidden)" in tape
    assert "mkdir -p demo" in tape and "# scene: files\n" in tape and "# scene: wrap" not in tape
