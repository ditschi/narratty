"""Finding the host engine's socket for ``sandbox.docker``."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from narratty.engine_access import engine_access, engine_socket
from narratty.errors import UsageError
from narratty.runtime import Runtime


def _podman(stdout: str, code: int = 0) -> Callable[[Sequence[str]], subprocess.CompletedProcess[str]]:
    def run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        assert argv[:2] == ["podman", "info"]
        return subprocess.CompletedProcess(argv, code, stdout, "")

    return run


def test_docker_socket() -> None:
    assert engine_socket(Runtime.DOCKER, environ={}) == "/var/run/docker.sock"
    rootless = {"DOCKER_HOST": "unix:///run/user/1000/docker.sock"}
    assert engine_socket(Runtime.DOCKER, environ=rootless) == "/run/user/1000/docker.sock"
    with pytest.raises(UsageError, match="local engine socket"):
        engine_socket(Runtime.DOCKER, environ={"DOCKER_HOST": "tcp://build:2375"})


def test_podman_socket() -> None:
    run = _podman("/run/user/1000/podman/podman.sock\n")
    assert engine_socket(Runtime.PODMAN, environ={}, run=run) == "/run/user/1000/podman/podman.sock"
    host = {"CONTAINER_HOST": "unix:///tmp/p.sock"}
    assert engine_socket(Runtime.PODMAN, environ=host, run=_podman("", 1)) == "/tmp/p.sock"
    with pytest.raises(UsageError, match="Podman API socket"):
        engine_socket(Runtime.PODMAN, environ={}, run=_podman("", 1))


def test_docker_joins_the_socket_group(tmp_path: Path) -> None:
    sock = tmp_path / "docker.sock"
    sock.touch()
    access = engine_access(Runtime.DOCKER, environ={"DOCKER_HOST": f"unix://{sock}"}, platform="linux")
    assert access.groups == (str(os.stat(sock).st_gid),)
    assert access.volume == f"{sock}:/run/docker.sock"
    assert access.env == {"DOCKER_HOST": "unix:///run/docker.sock"}
    desktop = engine_access(Runtime.DOCKER, environ={}, platform="darwin")
    assert (desktop.socket, desktop.groups) == ("/var/run/docker.sock", ("0",))
    with pytest.raises(UsageError, match="cannot use the Docker socket"):
        engine_access(Runtime.DOCKER, environ={"DOCKER_HOST": f"unix://{tmp_path}/no"}, platform="linux")


def test_rootless_podman_needs_no_group() -> None:
    access = engine_access(Runtime.PODMAN, environ={}, run=_podman("/run/p.sock"))
    assert access.groups == ()
