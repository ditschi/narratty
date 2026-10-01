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


@pytest.mark.parametrize(("mode", "written"), [("rw", True), ("snapshot", False)])
def test_container_build(tmp_path: Path, mode: str, written: bool) -> None:
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text(SPEC, encoding="utf-8")
    out = tmp_path / "out" / "demo.mp4"
    args = ["build", str(spec), "--runtime", "docker", "--workspace-mode", mode, "-o", str(out)]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    info = media.probe(out)
    assert info.has_video and info.has_audio
    # rw mounts the workspace itself; snapshot leaves it untouched.
    assert (tmp_path / "made-in-container").is_dir() is written


FEATURES = """\
terminal: {{width: 800, height: 400}}
workspace: {{mode: {mode}, artifacts: ["out/*.txt"], caches: {{demo: /var/cache/demo}}}}
sandbox:
  extra_mounts: [{{host: ./shared, container: /shared, mode: ro}}]
scenes:
  - id: work
    narration: The demo writes, reads a mount and keeps a cache.
    actions:
      - run: "mkdir -p out; cat /shared/hello.txt > out/result.txt; echo c > /var/cache/demo/c"
      - wait: {{prompt: true, timeout_ms: 20000}}
"""


def _build_in_container(spec: Path, out: Path, mode: str) -> None:
    args = ["build", str(spec), "--runtime", "docker", "--workspace-mode", mode, "--yes", "-o", str(out)]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert media.probe(out).has_video


def test_extra_mounts_artifacts_and_caches(tmp_path: Path) -> None:
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "hello.txt").write_text("from the host\n", encoding="utf-8")
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text(FEATURES.format(mode="snapshot"), encoding="utf-8")
    out = tmp_path / "out" / "demo.mp4"
    _build_in_container(spec, out, "snapshot")
    copied = out.parent / "demo.artifacts"
    assert (copied / "out" / "result.txt").read_text() == "from the host\n", "artifacts are copied out"
    assert not (tmp_path / "out" / "result.txt").exists(), "the snapshot keeps the checkout clean"


def test_read_only_workspace_is_enforced(tmp_path: Path) -> None:
    spec = tmp_path / "demo.narratty.yaml"
    run = "touch nope 2>/dev/null || echo blocked; echo done-$((6*7))"
    spec.write_text(
        "terminal: {width: 800, height: 400}\nscenes:\n  - id: a\n    narration: Read only.\n"
        f"    actions: [{{run: '{run}'}}]\n",
        encoding="utf-8",
    )
    _build_in_container(spec, tmp_path / "out" / "demo.mp4", "ro")
    assert not (tmp_path / "nope").exists()
