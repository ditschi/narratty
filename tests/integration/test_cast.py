"""``build --format cast`` with real Piper, bash and ffmpeg."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from narratty.build import CastOutputs, WorkspaceOptions, build_cast
from narratty.render import media

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not all(shutil.which(t) for t in ("ffmpeg", "ffprobe")), reason="needs ffmpeg"),
]

SPEC = """\
meta: {title: Cast}
end_card: {enabled: true, duration_ms: 1500}
scenes:
  - id: setup
    hidden: true
    actions: [{type_command: "mkdir -p demo && cd demo && touch one.txt two.txt"}, enter]
  - id: list
    narration: Here are the files.
    actions: [{type_command: "ls"}, enter, {wait: {screen: "one.txt"}}]
  - id: wrap
    narration: That is all.
"""


def test_build_cast(tmp_path: Path) -> None:
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text(SPEC, encoding="utf-8")
    result = build_cast(spec, workspace=WorkspaceOptions(mode="rw"))
    outputs = CastOutputs(result.output)
    assert result.output == tmp_path / "demo.html"
    events = [json.loads(line) for line in outputs.cast.read_text(encoding="utf-8").splitlines()[1:]]
    assert [e[2] for e in events if e[1] == "m"] == ["list", "wrap"]
    assert any("Created with narratty" in e[2] for e in events if e[1] == "o")
    audio = media.probe(outputs.audio)
    assert audio.has_audio and not audio.has_video
    assert abs(audio.duration_ms - result.video_ms) < 150, "narration covers the whole cast"
    assert abs(result.drift) < 0.05
    assert [p.scene_id for p in result.placements] == ["list", "wrap"]
    assert "data:audio/mpeg;base64," in result.output.read_text(encoding="utf-8")
