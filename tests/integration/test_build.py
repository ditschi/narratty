"""The full pipeline with real Piper, VHS and ffmpeg."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from narratty.build import build
from narratty.cli.app import app
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
    result = build(spec, work_dir=tmp_path / "work")
    info = media.probe(result.output)
    assert info.has_video and info.has_audio
    assert abs(result.drift) < 0.05, f"video {result.video_ms} ms vs plan {result.expected_ms} ms"
    assert abs(info.duration_ms - result.video_ms) < 200
    assert [p.scene_id for p in result.placements] == ["list", "wrap"]
    work = tmp_path / "work"
    assert {"scene.tape", "silent.mp4", "narration.wav"} <= {p.name for p in work.iterdir()}
    assert (spec.parent / "demo" / "one.txt").exists(), "the hidden setup ran in the workspace"


def test_build_command(spec: Path) -> None:
    result = CliRunner().invoke(app, ["build", str(spec), "-o", str(spec.parent / "out.mp4")])
    assert result.exit_code == 0, result.output
    assert (spec.parent / "out.mp4").is_file()
    assert "planned" in plain(result.output)
