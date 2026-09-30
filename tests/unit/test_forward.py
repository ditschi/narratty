"""The allowlist sidecar's TCP forwarder."""

from __future__ import annotations

import socket
import threading

import pytest

from narratty.forward import parse_rule, serve


def test_parse_rule() -> None:
    assert parse_rule("443=203.0.113.7:8443") == (443, "203.0.113.7", 8443)
    with pytest.raises(ValueError, match="invalid rule"):
        parse_rule("443:203.0.113.7")


def _echo_server() -> tuple[socket.socket, int]:
    server = socket.create_server(("127.0.0.1", 0))

    def loop() -> None:
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                while data := conn.recv(1024):
                    conn.sendall(data.upper())

    threading.Thread(target=loop, daemon=True).start()
    return server, server.getsockname()[1]


def test_forwards_both_directions() -> None:
    upstream, upstream_port = _echo_server()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        listen_port = probe.getsockname()[1]
    forwarder = serve(listen_port, "127.0.0.1", upstream_port, bind="127.0.0.1")
    try:
        with socket.create_connection(("127.0.0.1", listen_port), timeout=5) as client:
            client.sendall(b"hello")
            assert client.recv(1024) == b"HELLO"
    finally:
        forwarder.close()
        upstream.close()
