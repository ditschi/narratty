"""Reading devcontainer.json into an environment."""

from __future__ import annotations

from pathlib import Path

import pytest

from narratty.env_devcontainer import expand, parse_jsonc
from narratty.errors import UsageError
from narratty.spec.model import Environment


def _write(tmp_path: Path, text: str) -> Path:
    folder = tmp_path / "app" / ".devcontainer"
    folder.mkdir(parents=True)
    (folder / "devcontainer.json").write_text(text, encoding="utf-8")
    return tmp_path / "app"


def test_jsonc_comments_and_trailing_commas() -> None:
    text = '{\n  // a comment\n  "image": "x//y", /* block */\n  "list": [1, 2,],\n}\n'
    assert parse_jsonc(text) == {"image": "x//y", "list": [1, 2]}


def test_image_with_user_env_and_workspace_folder(tmp_path: Path) -> None:
    app = _write(
        tmp_path,
        '{"image": "mcr.microsoft.com/devcontainers/python:3", "remoteUser": "vscode",\n'
        ' "containerEnv": {"A": "1", "HOME_DIR": "${localEnv:HOME_DIR:/none}"},\n'
        ' "remoteEnv": {"B": "${containerWorkspaceFolder}"}}',
    )
    env = expand(Environment(devcontainer=".devcontainer"), app, env={})
    assert env.image == "mcr.microsoft.com/devcontainers/python:3"
    assert env.workdir == "/workspaces/app"
    assert env.user == "vscode"
    assert env.env == {"A": "1", "HOME_DIR": "/none", "B": "/workspaces/app"}
    assert expand(Environment(devcontainer=".devcontainer", user="host"), app).user == "host", "the spec wins"


def test_dockerfile_paths_are_relative_to_the_spec(tmp_path: Path) -> None:
    app = _write(
        tmp_path,
        '{"build": {"dockerfile": "Dockerfile", "context": "..", "args": {"V": 3}, "target": "dev"},\n'
        ' "workspaceFolder": "/src", "features": {"ghcr.io/x/y:1": {}}}',
    )
    notes: list[str] = []
    env = expand(Environment(devcontainer=".devcontainer/devcontainer.json"), app, log=notes.append)
    assert env.build is not None
    assert (env.build.context, env.build.dockerfile, env.build.target) == (
        ".",
        ".devcontainer/Dockerfile",
        "dev",
    )
    assert env.build.args == {"V": "3"}
    assert env.workdir == "/src"
    assert "features" in notes[0]


def test_compose_files_and_service(tmp_path: Path) -> None:
    app = _write(
        tmp_path,
        '{"dockerComposeFile": ["../compose.yaml", "compose.dev.yaml"], "service": "dev",'
        ' "workspaceFolder": "/workspace"}',
    )
    env = expand(Environment(devcontainer=".devcontainer", packages=["jq"]), app)
    assert env.compose is not None
    assert env.compose.file == ["compose.yaml", ".devcontainer/compose.dev.yaml"]
    assert (env.compose.service, env.workdir, env.packages) == ("dev", "/workspace", ["jq"])


def test_errors(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="no devcontainer.json"):
        expand(Environment(devcontainer="missing.json"), tmp_path)
    app = _write(tmp_path, '{"dockerComposeFile": "c.yaml"}')
    with pytest.raises(UsageError, match="no service"):
        expand(Environment(devcontainer=".devcontainer"), app)
    (app / ".devcontainer" / "devcontainer.json").write_text('{"name": "x"}', encoding="utf-8")
    with pytest.raises(UsageError, match="no image, build or dockerComposeFile"):
        expand(Environment(devcontainer=".devcontainer"), app)


def test_other_sources_pass_through(tmp_path: Path) -> None:
    env = Environment(image="x")
    assert expand(env, tmp_path) is env
