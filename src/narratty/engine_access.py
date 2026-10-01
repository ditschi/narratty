"""Hand the host's Docker or Podman engine to the demo (``sandbox.docker``).

The engine's socket is mounted into the narratty container, whose Docker CLI then
starts containers next to it on the host ("Docker outside of Docker"). Whoever
holds the socket controls the host, so this needs consent and can be locked by
policy (see ``narratty.sandbox``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from narratty.errors import UsageError
from narratty.runtime import Runtime

SOCKET_IN_CONTAINER = "/run/docker.sock"
DOCKER_DEFAULT_SOCKET = "/var/run/docker.sock"

Run = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), capture_output=True, text=True, check=False)  # noqa: S603


@dataclass(frozen=True)
class EngineAccess:
    """The socket to mount and the group the container needs to use it."""

    socket: str
    groups: tuple[str, ...] = ()

    @property
    def volume(self) -> str:
        """``--volume`` value."""
        return f"{self.socket}:{SOCKET_IN_CONTAINER}"

    @property
    def env(self) -> dict[str, str]:
        """Points the Docker CLI in the container at the socket."""
        return {"DOCKER_HOST": f"unix://{SOCKET_IN_CONTAINER}"}


def _unix_path(url: str, variable: str) -> str:
    if not url.startswith("unix://"):
        raise UsageError(
            f"sandbox.docker needs a local engine socket, but {variable} is {url}",
            hint="Unset it or point it at a unix:// socket.",
        )
    return url.removeprefix("unix://")


def engine_socket(engine: Runtime, *, environ: Mapping[str, str] | None = None, run: Run = _run) -> str:
    """Path of the engine's API socket, as the engine sees it (for ``--volume``).

    Docker: ``DOCKER_HOST`` or ``/var/run/docker.sock`` (Docker Desktop maps that path
    into its VM). Podman: ``CONTAINER_HOST`` or what ``podman info`` reports.
    """
    environ = os.environ if environ is None else environ
    if engine is Runtime.DOCKER:
        host = environ.get("DOCKER_HOST")
        return _unix_path(host, "DOCKER_HOST") if host else DOCKER_DEFAULT_SOCKET
    host = environ.get("CONTAINER_HOST")
    if host:
        return _unix_path(host, "CONTAINER_HOST")
    result = run(["podman", "info", "--format", "{{.Host.RemoteSocket.Path}}"])
    path = result.stdout.strip()
    if result.returncode != 0 or not path:
        raise UsageError(
            "cannot find the Podman API socket for sandbox.docker",
            hint="Enable it with `systemctl --user enable --now podman.socket`.",
        )
    return path.removeprefix("unix://")


def engine_access(
    engine: Runtime,
    *,
    environ: Mapping[str, str] | None = None,
    run: Run = _run,
    platform: str = sys.platform,
) -> EngineAccess:
    """What the container needs to use the host's engine.

    The container runs as your user. For rootful Docker on Linux it joins the
    socket's group (usually ``docker``); Docker Desktop's socket belongs to root's
    group. Rootless engines (Podman with ``keep-id``) need no extra group.
    """
    socket = engine_socket(engine, environ=environ, run=run)
    if engine is not Runtime.DOCKER:
        return EngineAccess(socket)
    if platform != "linux":
        return EngineAccess(socket, ("0",))
    try:
        gid = os.stat(socket).st_gid
    except OSError as error:
        raise UsageError(
            f"sandbox.docker: cannot use the Docker socket {socket}: {error.strerror}",
            hint="Is the Docker daemon running? Set DOCKER_HOST for a rootless daemon.",
        ) from error
    return EngineAccess(socket, (str(gid),))
