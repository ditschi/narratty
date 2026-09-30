"""Options shared by several subcommands."""

from __future__ import annotations

from enum import StrEnum

import typer

from narratty.runtime import Runtime

RuntimeOption = typer.Option(
    Runtime.AUTO,
    "--runtime",
    "-r",
    envvar="NARRATTY_RUNTIME",
    case_sensitive=False,
    help="Where to run: auto (container if available), native, docker or podman.",
)

OfflineOption = typer.Option(
    False, "--offline", envvar="NARRATTY_OFFLINE", help="Fail instead of downloading a missing voice."
)

ImageOption = typer.Option(
    None,
    "--image",
    envvar="NARRATTY_IMAGE",
    help="Container image to use (default: ghcr.io/ditschi/narratty matching this version).",
)


class WorkspaceMode(StrEnum):
    """Values of ``--workspace-mode``."""

    SNAPSHOT = "snapshot"
    RW = "rw"
    RO = "ro"


class NetworkMode(StrEnum):
    """Values of ``--network``."""

    NONE = "none"
    ALLOWLIST = "allowlist"
    FULL = "full"


WorkspaceModeOption = typer.Option(
    None, "--workspace-mode", help="Override workspace.mode: snapshot (throwaway copy), rw (in place) or ro."
)
KeepWorkspaceOption = typer.Option(False, "--keep-workspace", help="Keep the workspace snapshot afterwards.")
AllowDirtyOption = typer.Option(
    False, "--allow-dirty", help="Allow workspace.mode rw on a work tree with uncommitted changes."
)
NetworkOption = typer.Option(None, "--network", help="Override sandbox.network (containers only).")
AllowHostOption = typer.Option(
    None, "--allow-host", help="Allow HOST:PORT (implies --network allowlist); repeatable."
)
YesOption = typer.Option(
    False, "--yes", "-y", envvar="NARRATTY_YES", help="Approve the spec's sandbox permissions without asking."
)


def check_hosts(hosts: list[str] | None) -> tuple[str, ...]:
    """Validate ``--allow-host`` values."""
    import re

    from narratty.errors import UsageError
    from narratty.spec.model import HOST_PORT_PATTERN

    for host in hosts or []:
        if not re.match(HOST_PORT_PATTERN, host):
            raise UsageError(f"--allow-host {host!r} is not HOST:PORT")
    return tuple(hosts or ())


EndCardOption = typer.Option(
    None,
    "--end-card/--no-end-card",
    help='Show the closing "Created with narratty" card (default: the spec, then your config, then on).',
    show_default=False,
)
