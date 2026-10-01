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


def test_exit_codes_are_checked_in_the_environment(tmp_path: Path) -> None:
    from narratty.errors import CommandError

    spec = _spec(tmp_path)
    run = "      - run: test -e nothing-here\n"
    spec.write_text(SPEC.replace("      - wait", run + "      - wait"), encoding="utf-8")
    with pytest.raises(CommandError, match="`test -e nothing-here` exited with 1"):
        build_cast(spec, workspace=WorkspaceOptions(mode="rw"), sandbox=SandboxRequest())
    build_cast(spec, workspace=WorkspaceOptions(mode="rw"), sandbox=SandboxRequest(), ignore_exit=True)


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


def test_packages_and_setup(tmp_path: Path) -> None:
    (tmp_path / "Dockerfile").write_text(f"FROM {IMAGE}\nRUN useradd -u 1500 dev\nUSER dev\n")
    subprocess.run(["docker", "build", "--quiet", "--tag", "narratty-test-dev", str(tmp_path)], check=True)
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text(
        "environment:\n  image: narratty-test-dev\n  packages: [jq]\n  setup: ['echo made > /etc/demo']\n"
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


def _cast_output(spec: Path, mode: str = "rw") -> str:
    result = build_cast(spec, workspace=WorkspaceOptions(mode=mode), sandbox=SandboxRequest(assume_yes=True))
    events = [json.loads(line) for line in CastOutputs(result.output).cast.read_text().splitlines()[1:]]
    return "".join(e[2] for e in events if e[1] == "o")


def test_compose_service(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text(
        f"services:\n  dev:\n    image: {IMAGE}\n    command: sleep infinity\n"
        "    volumes: ['.:/src']\n    working_dir: /src\n",
        encoding="utf-8",
    )
    spec = tmp_path / "demo.narratty.yaml"
    spec.write_text(SPEC.replace(f'{{image: "{IMAGE}"}}', "{compose: {service: dev}}"), encoding="utf-8")
    output = _cast_output(spec)
    assert "in-42" in output
    assert (tmp_path / "made-in-env").is_file(), "the service's own mounts point at the workspace"
    left = subprocess.run(
        ["docker", "ps", "--all", "--quiet", "--filter", "label=narratty.environment=1"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert left.stdout.strip() == "", "the project is removed"


def test_running_container(tmp_path: Path) -> None:
    name = f"narratty-test-{os.getpid()}"
    subprocess.run(
        ["docker", "run", "--detach", "--name", name, "--volume", f"{tmp_path}:/src", "--workdir", "/src",
         IMAGE, "sleep", "infinity"],
        check=True, capture_output=True,
    )  # fmt: skip
    try:
        spec = tmp_path / "demo.narratty.yaml"
        spec.write_text(
            "workspace: {mode: rw}\n"
            + SPEC.replace(f'{{image: "{IMAGE}"}}', f"{{container: {name}, user: image}}"),
            encoding="utf-8",
        )
        assert "in-42" in _cast_output(spec)
        assert (tmp_path / "made-in-env").is_file()
        running = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", name], capture_output=True, text=True
        )
        assert running.stdout.strip() == "true", "narratty leaves the container running"
    finally:
        subprocess.run(["docker", "rm", "--force", name], check=False, capture_output=True)


def test_env_up_is_reused_until_down(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    runner = CliRunner()
    up = runner.invoke(
        app, ["env", "up", str(spec), "--workspace-mode", "rw", "--runtime", "native", "--yes"]
    )
    assert up.exit_code == 0, up.output
    container = up.stdout.strip().splitlines()[-1]
    try:
        assert "in-42" in _cast_output(spec)
        again = runner.invoke(app, ["env", "up", str(spec), "--runtime", "native"])
        assert again.stdout.strip().splitlines()[-1] == container, "already running"
    finally:
        down = runner.invoke(app, ["env", "down", str(spec), "--runtime", "native"])
    assert down.exit_code == 0, down.output
    left = subprocess.run(
        ["docker", "ps", "--all", "--quiet", "--filter", f"id={container}"], capture_output=True, text=True
    )
    assert left.stdout.strip() == ""


def test_devcontainer_example(tmp_path: Path) -> None:
    example = Path(__file__).parents[2] / "examples" / "devcontainer"
    project = tmp_path / "project"
    shutil.copytree(example, project)
    output = _cast_output(project / "demo.narratty.yaml", mode="snapshot")
    assert "APP_ENV=demo" in output and "/workspace" in output
    assert "build finished" in output and "all green" in output, "waited for the build"
    assert not (project / "dist").exists(), "the build wrote into the snapshot"
