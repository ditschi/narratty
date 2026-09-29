"""Tiny TCP forwarder used by the ``network: allowlist`` sidecar.

``python -m narratty.forward 443=203.0.113.7:443 27000=203.0.113.7:27000`` listens on
each local port and passes connections through to the target unchanged (so TLS,
SNI and certificates stay intact). Standard library only.
"""

from __future__ import annotations

import contextlib
import socket
import sys
import threading
from collections.abc import Sequence

BUFFER = 64 * 1024


def parse_rule(rule: str) -> tuple[int, str, int]:
    """``443=203.0.113.7:443`` → ``(443, "203.0.113.7", 443)``."""
    listen, _, target = rule.partition("=")
    host, _, port = target.rpartition(":")
    if not (listen.isdigit() and host and port.isdigit()):
        raise ValueError(f"invalid rule {rule!r}, expected LISTEN_PORT=HOST:PORT")
    return int(listen), host.strip("[]"), int(port)


def _pump(source: socket.socket, sink: socket.socket) -> None:
    try:
        while data := source.recv(BUFFER):
            sink.sendall(data)
    except OSError:
        pass
    finally:
        for sock, how in ((sink, socket.SHUT_WR), (source, socket.SHUT_RD)):
            with contextlib.suppress(OSError):
                sock.shutdown(how)


def _handle(client: socket.socket, host: str, port: int) -> None:
    try:
        upstream = socket.create_connection((host, port), timeout=15)
    except OSError as error:
        print(f"narratty-forward: cannot reach {host}:{port}: {error}", file=sys.stderr, flush=True)
        client.close()
        return
    upstream.settimeout(None)
    with client, upstream:
        back = threading.Thread(target=_pump, args=(upstream, client), daemon=True)
        back.start()
        _pump(client, upstream)
        back.join()


def serve(listen_port: int, host: str, port: int, *, bind: str = "0.0.0.0") -> socket.socket:  # noqa: S104
    """Start forwarding in a background thread; returns the listening socket."""
    server = socket.create_server((bind, listen_port), reuse_port=False)

    def accept_loop() -> None:
        while True:
            try:
                client, _ = server.accept()
            except OSError:
                return
            threading.Thread(target=_handle, args=(client, host, port), daemon=True).start()

    threading.Thread(target=accept_loop, daemon=True).start()
    return server


def main(argv: Sequence[str] | None = None) -> None:
    """Forward every rule until the process is stopped."""
    rules = [parse_rule(rule) for rule in (sys.argv[1:] if argv is None else argv)]
    if not rules:
        raise SystemExit("usage: python -m narratty.forward LISTEN_PORT=HOST:PORT ...")
    for listen_port, host, port in rules:
        serve(listen_port, host, port)
        print(f"narratty-forward: :{listen_port} -> {host}:{port}", flush=True)
    threading.Event().wait()


if __name__ == "__main__":
    main()
