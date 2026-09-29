"""`build --runtime docker` against a locally built image (set NARRATTY_IMAGE)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from narratty.cli.app import app
from narratty.render import media

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("NARRATTY_IMAGE") and shutil.which("docker")),
        reason="needs docker and NARRATTY_IMAGE pointing at a narratty image",
    ),
]

SPEC = """\
terminal: {width: 800, height: 400}
scenes:
  - id: setup
    hidden: true
    actions: [{type_command: "mkdir -p made-in-container"}, enter]
  - id: hello
    narration: This video was recorded inside the narratty container.
    actions: [{type_command: "whoami; ls"}, enter]
"""


def test_container_build(tmp_path: Path) -> None:
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text(SPEC, encoding="utf-8")
    out = tmp_path / "out" / "demo.mp4"
    result = CliRunner().invoke(app, ["build", str(spec), "--runtime", "docker", "-o", str(out)])
    assert result.exit_code == 0, result.output
    info = media.probe(out)
    assert info.has_video and info.has_audio
    assert (tmp_path / "made-in-container").is_dir(), "the workspace is mounted into the container"
