"""`network: allowlist` with real containers (set NARRATTY_IMAGE)."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading
from collections.abc import Iterator

import pytest

from narratty.sandbox import allowlist_network

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("NARRATTY_IMAGE") and shutil.which("docker")),
        reason="needs docker and NARRATTY_IMAGE pointing at a narratty image",
    ),
]

PROBE = """
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
try:
    with socket.create_connection((host, port), timeout=5) as s:
        s.sendall(b"ping")
        print(s.recv(64).decode())
except OSError as error:
    print(f"blocked: {error}")
"""


@pytest.fixture
def upstream() -> Iterator[tuple[str, int]]:
    """A TCP server on the host that answers PONG, reachable from the docker bridge."""
    gateway = subprocess.run(
        ["docker", "network", "inspect", "bridge", "--format", "{{(index .IPAM.Config 0).Gateway}}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    server = socket.create_server(("0.0.0.0", 0))  # noqa: S104

    def loop() -> None:
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                conn.recv(64)
                conn.sendall(b"PONG")

    threading.Thread(target=loop, daemon=True).start()
    yield gateway, server.getsockname()[1]
    server.close()


def _probe(network: str, host: str, port: int) -> str:
    image = os.environ["NARRATTY_IMAGE"]
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            network,
            "--entrypoint",
            "python",
            image,
            "-c",
            PROBE,
            host,
            str(port),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return (result.stdout + result.stderr).strip()


def test_allowlisted_host_is_reachable_and_nothing_else(upstream: tuple[str, int]) -> None:
    gateway, port = upstream
    image = os.environ["NARRATTY_IMAGE"]
    with allowlist_network("docker", image, [f"upstream.test:{port}"], resolver=lambda _host: gateway) as net:
        assert _probe(net, "upstream.test", port) == "PONG"
        assert _probe(net, gateway, port).startswith("blocked"), "direct access bypassing the allowlist"
        assert _probe(net, "example.com", 443).startswith("blocked")
    networks = subprocess.run(
        ["docker", "network", "ls", "--format", "{{.Name}}"], capture_output=True, text=True
    )
    assert net not in networks.stdout, "the sandbox network is removed afterwards"


def test_no_network(upstream: tuple[str, int]) -> None:
    gateway, port = upstream
    assert _probe("none", gateway, port).startswith("blocked")
