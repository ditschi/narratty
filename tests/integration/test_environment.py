"""Demos in a project environment: a plain Debian image, natively and from the container."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from narratty.build import CastOutputs, WorkspaceOptions, build, build_cast
from narratty.cli.app import app
from narratty.container import SandboxRequest
from narratty.render import media

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not shutil.which("docker"), reason="needs docker"),
    pytest.mark.skipif(not all(shutil.which(t) for t in ("ffmpeg", "ffprobe")), reason="needs ffmpeg"),
]

IMAGE = os.environ.get("NARRATTY_TEST_ENV_IMAGE", "debian:trixie-slim")

SPEC = f"""\
meta: {{title: Environment}}
terminal: {{width: 800, height: 400}}
environment: {{image: "{IMAGE}"}}
end_card: {{enabled: true, duration_ms: 1500}}
scenes:
  - id: where
    narration: This shell runs in the project image.
    actions:
      - type_command: "echo in-$((6*7)) && touch made-in-env"
      - enter
      - wait: {{screen: "in-42"}}
"""


def _spec(tmp_path: Path) -> Path:
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text(SPEC, encoding="utf-8")
    return spec


def test_cast_natively(tmp_path: Path) -> None:
    result = build_cast(_spec(tmp_path), workspace=WorkspaceOptions(mode="rw"), sandbox=SandboxRequest())
    events = [json.loads(line) for line in CastOutputs(result.output).cast.read_text().splitlines()[1:]]
    output = "".join(e[2] for e in events if e[1] == "o")
    assert "Created with narratty" in output, "the card is drawn outside the environment"
    assert (tmp_path / "made-in-env").is_file(), "the workspace is mounted at /work"


@pytest.mark.skipif(not all(shutil.which(t) for t in ("vhs", "ttyd")), reason="needs vhs and ttyd")
def test_video_natively(tmp_path: Path) -> None:
    result = build(_spec(tmp_path), workspace=WorkspaceOptions(mode="rw"), sandbox=SandboxRequest())
    info = media.probe(result.output)
    assert info.has_video and info.has_audio
    assert (tmp_path / "made-in-env").is_file()


@pytest.mark.skipif(not os.environ.get("NARRATTY_IMAGE"), reason="needs NARRATTY_IMAGE")
def test_video_from_the_container(tmp_path: Path) -> None:
    out = tmp_path / "out" / "demo.mp4"
    args = ["build", str(_spec(tmp_path)), "--runtime", "docker", "--workspace-mode", "rw", "-o", str(out)]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    info = media.probe(out)
    assert info.has_video and info.has_audio
    assert (tmp_path / "made-in-env").is_file()


def test_packages_and_build(tmp_path: Path) -> None:
    (tmp_path / "Dockerfile").write_text(f"FROM {IMAGE}\nRUN useradd -u 1500 dev\nUSER dev\n")
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text(
        "environment:\n  build: {context: .}\n  packages: [jq]\n  setup: ['echo made > /etc/demo']\n"
        "scenes: [{id: a}]\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(app, ["env", "build", str(spec), "--yes"])
    assert result.exit_code == 0, result.output
    tag = result.stdout.strip().splitlines()[-1]
    assert tag.startswith("narratty-env:")
    check = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "sh", tag, "-c", "id -u; jq --version; cat /etc/demo"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert check.stdout.split()[0] == "1500", "back to the image's user"
    assert "jq-" in check.stdout and "made" in check.stdout
    again = runner.invoke(app, ["env", "build", str(spec)])
    assert again.stdout.strip().splitlines()[-1] == tag, "cached"
